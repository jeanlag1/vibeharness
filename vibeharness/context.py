"""Context window management.

- Counts tokens with tiktoken (close enough for budgeting; Anthropic
  doesn't ship a public tokenizer in the SDK).
- Compacts conversation history when it exceeds a threshold by asking
  the model itself to summarize the older portion.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .llm import LLMProvider

try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover
    _ENC = None


def count_tokens_text(text: str) -> int:
    if _ENC is None:
        return max(1, len(text) // 4)
    return len(_ENC.encode(text))


def _flatten_message(msg: dict) -> str:
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                parts.append(str(block)); continue
            t = block.get("type")
            if t == "text":
                parts.append(block.get("text", ""))
            elif t == "tool_use":
                parts.append(f"[tool_use {block.get('name')} {json.dumps(block.get('input', {}))[:200]}]")
            elif t == "tool_result":
                c = block.get("content", "")
                if isinstance(c, list):
                    c = " ".join(str(x) for x in c)
                parts.append(f"[tool_result {str(c)[:400]}]")
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content or "")


def count_tokens_messages(messages: list[dict]) -> int:
    return sum(count_tokens_text(_flatten_message(m)) for m in messages)


@dataclass
class ContextManager:
    max_tokens: int = 120_000
    compact_threshold: float = 0.75  # compact when usage exceeds this fraction
    keep_recent: int = 6              # keep this many most-recent turns intact

    def needs_compaction(self, messages: list[dict]) -> bool:
        return count_tokens_messages(messages) > self.max_tokens * self.compact_threshold

    def compact(self, provider: "LLMProvider", messages: list[dict]) -> list[dict]:
        """Summarize the older portion of `messages` via the provider.

        Keeps the last `keep_recent` messages verbatim. Replaces everything
        before with a single 'user' message containing a summary.
        """
        if len(messages) <= self.keep_recent:
            return messages
        head = messages[:-self.keep_recent]
        tail = messages[-self.keep_recent:]
        transcript = "\n\n".join(f"[{m.get('role','?')}] {_flatten_message(m)[:2000]}" for m in head)
        summary_request = (
            "Summarize the conversation below into a concise brief that preserves: "
            "the user's goal(s), key decisions made, files read or modified, and any "
            "facts the assistant should remember to continue the task. Be specific "
            "about file paths and what changed. Output plain prose, ~300 words max.\n\n"
            f"---\n{transcript}\n---"
        )
        from .llm import AnthropicProvider, OpenAIProvider
        if isinstance(provider, OpenAIProvider):
            messages_for_summary = [{"role": "user", "content": summary_request}]
        else:
            messages_for_summary = [{"role": "user", "content": [{"type": "text", "text": summary_request}]}]
        turn = provider.complete(
            system="You produce faithful, concise conversation summaries.",
            messages=messages_for_summary,
            tools=[],
            max_tokens=1024,
        )
        summary_text = (turn.text or "").strip() or "(prior context omitted)"
        if isinstance(provider, OpenAIProvider):
            primer = {"role": "user", "content": f"[summary of earlier conversation]\n{summary_text}"}
        else:
            primer = {"role": "user", "content": [{"type": "text", "text": f"[summary of earlier conversation]\n{summary_text}"}]}
        return [primer] + tail
