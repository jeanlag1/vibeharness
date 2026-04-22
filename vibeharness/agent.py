"""The agent loop: tie LLM, tools, and permissions together."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from .llm import AnthropicProvider, AssistantTurn, LLMProvider, OpenAIProvider, ToolCall
from .permissions import PermissionPolicy
from .prompts import build_system_prompt
from .tools import Tool, build_default_registry, dispatch

if TYPE_CHECKING:  # pragma: no cover
    from .hooks import HookManager


# Hook signatures for UI integration. All optional.
OnAssistantText = Callable[[str], None]
OnToolStart = Callable[[ToolCall], None]
OnToolEnd = Callable[[ToolCall, dict], None]
OnTurnEnd = Callable[[AssistantTurn], None]


@dataclass
class AgentHooks:
    on_assistant_text: Optional[OnAssistantText] = None
    on_text_delta: Optional[Callable[[str], None]] = None
    on_tool_start: Optional[OnToolStart] = None
    on_tool_end: Optional[OnToolEnd] = None
    on_turn_end: Optional[OnTurnEnd] = None
    on_request_start: Optional[Callable[[], None]] = None
    on_request_end: Optional[Callable[[], None]] = None


@dataclass
class Agent:
    provider: LLMProvider
    tools: dict[str, Tool] = field(default_factory=build_default_registry)
    system_prompt: str = field(default_factory=build_system_prompt)
    permissions: PermissionPolicy = field(default_factory=PermissionPolicy)
    hooks: AgentHooks = field(default_factory=AgentHooks)
    messages: list[dict] = field(default_factory=list)
    max_iters: int = 50
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens: int = 0
    total_cache_write_tokens: int = 0
    last_stop_reason: Optional[str] = None
    hook_manager: Optional["HookManager"] = None
    on_checkpoint: Optional[Callable[[], None]] = None

    # ------------------------------------------------------------------ public
    def add_user_message(self, text: str) -> None:
        if isinstance(self.provider, OpenAIProvider):
            self.messages.append({"role": "user", "content": text})
        else:
            self.messages.append({"role": "user", "content": [{"type": "text", "text": text}]})

    def run(self, user_input: str) -> AssistantTurn:
        """Run one user-input -> assistant-final-response cycle."""
        self.add_user_message(user_input)
        last_turn: Optional[AssistantTurn] = None

        for _ in range(self.max_iters):
            if self.hooks.on_request_start:
                try: self.hooks.on_request_start()
                except Exception: pass

            # Wrap text-delta to auto-stop the thinking spinner on first token.
            _wrapped_delta = self.hooks.on_text_delta
            if _wrapped_delta and self.hooks.on_request_end:
                _stopped = {"v": False}
                _user_cb = self.hooks.on_text_delta
                _end_cb = self.hooks.on_request_end
                def _wrapped_delta(d, _u=_user_cb, _e=_end_cb, _s=_stopped):
                    if not _s["v"]:
                        _s["v"] = True
                        try: _e()
                        except Exception: pass
                    _u(d)

            try:
                turn = self.provider.complete(
                    system=self.system_prompt,
                    messages=self.messages,
                    tools=list(self.tools.values()),
                    on_text_delta=_wrapped_delta,
                )
            finally:
                if self.hooks.on_request_end:
                    try: self.hooks.on_request_end()
                    except Exception: pass
            last_turn = turn
            self.last_stop_reason = turn.stop_reason
            self.total_input_tokens += turn.usage.get("input_tokens", 0)
            self.total_output_tokens += turn.usage.get("output_tokens", 0)
            self.total_cache_read_tokens += turn.usage.get("cache_read_input_tokens", 0)
            self.total_cache_write_tokens += turn.usage.get("cache_creation_input_tokens", 0)

            if turn.text and self.hooks.on_assistant_text and not self.hooks.on_text_delta:
                # When streaming, deltas have already been delivered; don't repeat the full text.
                self.hooks.on_assistant_text(turn.text)

            self.messages.append(self._format_assistant(turn))

            if not turn.tool_calls:
                # Detect truncation: model wanted to keep going but hit max_tokens.
                if turn.stop_reason == "max_tokens":
                    if self.hooks.on_turn_end:
                        self.hooks.on_turn_end(turn)
                    # Nudge the model to continue.
                    self.add_user_message(
                        "Your previous response was cut off at the output token limit. "
                        "Please continue from where you left off."
                    )
                    continue
                if self.hooks.on_turn_end:
                    self.hooks.on_turn_end(turn)
                return turn

            results = self._execute_tools(turn.tool_calls)
            self._append_tool_results(results)

            # Mid-turn checkpoint: persist after every tool round so a crash
            # or Ctrl-C can be resumed from the latest tool result.
            if self.on_checkpoint:
                try:
                    self.on_checkpoint()
                except Exception:
                    pass

            if self.hooks.on_turn_end:
                self.hooks.on_turn_end(turn)

        # Hit iteration cap.
        return last_turn or AssistantTurn(text="(no response)")

    # ------------------------------------------------------------- internals
    def _format_assistant(self, turn: AssistantTurn) -> dict:
        if isinstance(self.provider, OpenAIProvider):
            return OpenAIProvider.format_assistant_message(turn)
        return AnthropicProvider.format_assistant_message(turn)

    def _execute_tools(self, calls: list[ToolCall]) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []
        for tc in calls:
            tool = self.tools.get(tc.name)
            mutating = bool(tool and tool.mutating)
            if self.hooks.on_request_end:
                try: self.hooks.on_request_end()
                except Exception: pass
            allowed, reason = self.permissions.check(tc.name, mutating, tc.args)
            if self.hooks.on_tool_start:
                self.hooks.on_tool_start(tc)
            if not allowed:
                payload = {"error": reason}
            else:
                args = tc.args
                override: Optional[dict] = None
                if self.hook_manager:
                    args, override = self.hook_manager.run_before(tc.name, args)
                if override is not None:
                    payload = override
                else:
                    payload = dispatch(self.tools, tc.name, args)
                    if self.hook_manager:
                        payload = self.hook_manager.run_after(tc.name, args, payload)
            if self.hooks.on_tool_end:
                self.hooks.on_tool_end(tc, payload)
            results.append((tc.id, _serialize(payload)))
        return results

    def _append_tool_results(self, results: list[tuple[str, str]]) -> None:
        if isinstance(self.provider, OpenAIProvider):
            self.messages.extend(OpenAIProvider.format_tool_results(results))
        else:
            self.messages.append(AnthropicProvider.format_tool_results(results))


def _serialize(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(payload)
