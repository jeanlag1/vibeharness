"""Permission policy for tool calls.

Three modes:
- "auto"  : approve everything (CI, "/god" mode)
- "ask"   : prompt user on mutating tools, remember per-tool decisions
- "deny"  : refuse all mutating tools (read-only inspection mode)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

Mode = Literal["auto", "ask", "deny"]

Prompter = Callable[[str, dict], str]
"""Called as prompter(tool_name, args) -> 'allow' | 'allow_always' | 'deny'."""


@dataclass
class PermissionPolicy:
    mode: Mode = "ask"
    prompter: Prompter | None = None
    always_allow: set[str] = field(default_factory=set)

    def check(self, tool_name: str, mutating: bool, args: dict) -> tuple[bool, str | None]:
        """Returns (allowed, denial_reason)."""
        if not mutating or self.mode == "auto":
            return True, None
        if tool_name in self.always_allow:
            return True, None
        if self.mode == "deny":
            return False, f"tool '{tool_name}' is denied (read-only mode)"
        # ask
        if self.prompter is None:
            return True, None  # no UI hooked up; permit
        decision = self.prompter(tool_name, args)
        if decision == "allow":
            return True, None
        if decision == "allow_always":
            self.always_allow.add(tool_name)
            return True, None
        return False, f"user denied '{tool_name}'"
