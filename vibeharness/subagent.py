"""Sub-agent / Task tool.

Spawns a fresh `Agent` to handle an isolated subtask (e.g. exploring a
codebase, summarizing test failures). The sub-agent runs to completion
in its own message history; only its final text is returned to the parent.

This keeps the parent conversation small even when investigation is large
— the single most important pattern for staying focused on long tasks.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover
    from .agent import Agent
    from .llm import LLMProvider
    from .tools import Tool


SUBAGENT_SYSTEM = """You are a sub-agent spawned by the main agent to perform a focused subtask. Work autonomously, use tools as needed, and finish with a CONCISE final report (a few sentences to a short bullet list). Do not ask the parent agent questions."""


def make_task_tool(
    provider: "LLMProvider",
    parent_tools: Optional[dict[str, "Tool"]] = None,
    max_iters: int = 30,
):
    """Return a `task` Tool that spawns a sub-agent on demand.

    The sub-agent inherits the parent's tool registry minus this `task`
    tool itself (no recursive spawning by default — keeps cost bounded).
    """
    from .agent import Agent
    from .permissions import PermissionPolicy
    from .tools import Tool, build_default_registry

    def _spawn(description: str, allowed_tools: Optional[list[str]] = None) -> dict:
        base = dict(parent_tools) if parent_tools else build_default_registry()
        base.pop("task", None)  # no recursion
        if allowed_tools:
            base = {n: t for n, t in base.items() if n in set(allowed_tools)}
        sub = Agent(
            provider=provider,
            tools=base,
            system_prompt=SUBAGENT_SYSTEM,
            permissions=PermissionPolicy(mode="auto"),
            max_iters=max_iters,
        )
        final = sub.run(description)
        return {
            "report": final.text or "(no report)",
            "iterations": len([m for m in sub.messages if m.get("role") == "assistant"]),
            "input_tokens": sub.total_input_tokens,
            "output_tokens": sub.total_output_tokens,
        }

    return Tool(
        name="task",
        description=(
            "Spawn an autonomous sub-agent to handle an isolated subtask. "
            "Use this for read-heavy investigations (e.g. 'find all callers of "
            "function foo and summarize') so the main conversation stays small. "
            "The sub-agent has its own tool access and returns only a final report. "
            "Optionally restrict its tools via `allowed_tools` (e.g. ['read_file', 'grep'])."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Self-contained task description for the sub-agent.",
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional whitelist of tool names. Default: all parent tools.",
                },
            },
            "required": ["description"],
        },
        func=lambda **kw: _spawn(**kw),
        mutating=False,
    )
