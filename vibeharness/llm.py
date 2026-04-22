"""LLM provider abstraction.

The agent loop only knows about `LLMProvider`. Anthropic is the reference
implementation; OpenAI is included as an optional alternative. Both translate
to a common `(text_blocks, tool_calls)` shape per assistant turn.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Protocol

from .tools import Tool

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"
DEFAULT_OPENAI_MODEL = "gpt-4.1"


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class AssistantTurn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: Optional[str] = None
    usage: dict = field(default_factory=dict)
    raw: Any = None


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[Tool],
        max_tokens: int = 4096,
        on_text_delta: Optional[Callable[[str], None]] = None,
    ) -> AssistantTurn: ...


# ----------------------------------------------------------------------------
# Anthropic
# ----------------------------------------------------------------------------
class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str = DEFAULT_ANTHROPIC_MODEL, api_key: Optional[str] = None,
                 enable_prompt_caching: bool = True):
        try:
            from anthropic import Anthropic
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("anthropic package required") from e
        self.client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model
        self.enable_prompt_caching = enable_prompt_caching

    def _system_blocks(self, system: str) -> list[dict]:
        block: dict = {"type": "text", "text": system}
        if self.enable_prompt_caching:
            block["cache_control"] = {"type": "ephemeral"}
        return [block]

    def _tool_blocks(self, tools) -> list[dict]:
        out = [t.to_anthropic() for t in tools]
        if self.enable_prompt_caching and out:
            # Cache breakpoint on the LAST tool entry covers all tool defs.
            out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
        return out

    def complete(self, system, messages, tools, max_tokens=4096, on_text_delta=None):
        if on_text_delta is None:
            return self._complete_blocking(system, messages, tools, max_tokens)
        return self._complete_streaming(system, messages, tools, max_tokens, on_text_delta)

    def _complete_blocking(self, system, messages, tools, max_tokens):
        resp = self.client.messages.create(
            model=self.model,
            system=self._system_blocks(system),
            messages=messages,
            tools=self._tool_blocks(tools),
            max_tokens=max_tokens,
        )
        return self._build_turn(resp)

    def _complete_streaming(self, system, messages, tools, max_tokens, on_text_delta):
        with self.client.messages.stream(
            model=self.model,
            system=self._system_blocks(system),
            messages=messages,
            tools=self._tool_blocks(tools),
            max_tokens=max_tokens,
        ) as stream:
            for event in stream:
                if event.type == "content_block_delta" and getattr(event.delta, "type", "") == "text_delta":
                    on_text_delta(event.delta.text)
            resp = stream.get_final_message()
        return self._build_turn(resp)

    def _build_turn(self, resp) -> "AssistantTurn":
        text = ""
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, args=dict(block.input)))
        usage = {
            "input_tokens": getattr(resp.usage, "input_tokens", 0),
            "output_tokens": getattr(resp.usage, "output_tokens", 0),
            "cache_read_input_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
        }
        return AssistantTurn(
            text=text,
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason,
            usage=usage,
            raw=resp,
        )

    @staticmethod
    def format_assistant_message(turn: AssistantTurn) -> dict:
        content: list[dict] = []
        if turn.text:
            content.append({"type": "text", "text": turn.text})
        for tc in turn.tool_calls:
            content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.args})
        return {"role": "assistant", "content": content}

    @staticmethod
    def format_tool_results(results: list[tuple[str, str]]) -> dict:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": out}
                for tid, out in results
            ],
        }


# ----------------------------------------------------------------------------
# OpenAI (optional)
# ----------------------------------------------------------------------------
class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str = DEFAULT_OPENAI_MODEL, api_key: Optional[str] = None):
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("openai extra not installed: pip install vibeharness[openai]") from e
        self.client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self.model = model

    def complete(self, system, messages, tools, max_tokens=4096, on_text_delta=None):
        msgs = [{"role": "system", "content": system}] + messages
        if on_text_delta is None:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=msgs,
                tools=[t.to_openai() for t in tools] or None,
                max_tokens=max_tokens,
            )
        else:
            # Streaming path
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=msgs,
                tools=[t.to_openai() for t in tools] or None,
                max_tokens=max_tokens,
                stream=True,
                stream_options={"include_usage": True},
            )
            text_acc = ""
            tool_acc: dict[int, dict] = {}
            finish = None
            usage_out = None
            for chunk in stream:
                if chunk.usage:
                    usage_out = chunk.usage
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    text_acc += delta.content
                    on_text_delta(delta.content)
                for tc in (delta.tool_calls or []):
                    slot = tool_acc.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if tc.id: slot["id"] = tc.id
                    if tc.function and tc.function.name: slot["name"] = tc.function.name
                    if tc.function and tc.function.arguments: slot["args"] += tc.function.arguments
                if chunk.choices[0].finish_reason:
                    finish = chunk.choices[0].finish_reason

            import json as _json
            tool_calls = [
                ToolCall(id=v["id"], name=v["name"], args=_json.loads(v["args"] or "{}"))
                for v in tool_acc.values()
            ]
            return AssistantTurn(
                text=text_acc,
                tool_calls=tool_calls,
                stop_reason=finish,
                usage={
                    "input_tokens": getattr(usage_out, "prompt_tokens", 0) if usage_out else 0,
                    "output_tokens": getattr(usage_out, "completion_tokens", 0) if usage_out else 0,
                },
                raw=None,
            )

        choice = resp.choices[0]
        msg = choice.message
        tool_calls = []
        for tc in msg.tool_calls or []:
            import json

            tool_calls.append(
                ToolCall(id=tc.id, name=tc.function.name, args=json.loads(tc.function.arguments or "{}"))
            )
        usage = {
            "input_tokens": resp.usage.prompt_tokens,
            "output_tokens": resp.usage.completion_tokens,
        }
        return AssistantTurn(
            text=msg.content or "",
            tool_calls=tool_calls,
            stop_reason=choice.finish_reason,
            usage=usage,
            raw=resp,
        )

    @staticmethod
    def format_assistant_message(turn: AssistantTurn) -> dict:
        msg: dict = {"role": "assistant", "content": turn.text or None}
        if turn.tool_calls:
            import json

            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
                }
                for tc in turn.tool_calls
            ]
        return msg

    @staticmethod
    def format_tool_results(results: list[tuple[str, str]]) -> list[dict]:
        return [{"role": "tool", "tool_call_id": tid, "content": out} for tid, out in results]


def make_provider(name: str = "anthropic", model: Optional[str] = None) -> LLMProvider:
    if name == "anthropic":
        return AnthropicProvider(model=model or DEFAULT_ANTHROPIC_MODEL)
    if name == "openai":
        return OpenAIProvider(model=model or DEFAULT_OPENAI_MODEL)
    raise ValueError(f"unknown provider: {name}")
