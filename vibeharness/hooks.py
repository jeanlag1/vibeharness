"""Pre/post-tool hooks (extensibility API).

Users register Python callables that run before and after every tool call.
Hooks live at ~/.vibe/hooks.py:

    # ~/.vibe/hooks.py
    def before_tool(name, args):
        # mutate args, raise to deny, or return None
        if name == "edit_file" and args["path"].endswith(".env"):
            raise PermissionError("no .env edits")
        return args  # or modified

    def after_tool(name, args, result):
        # observe or transform results
        return result

The CLI loads them automatically. Multiple before/after hooks may be
registered programmatically via HookManager.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

HOOKS_PATH = Path.home() / ".vibe" / "hooks.py"

BeforeHook = Callable[[str, dict], Optional[dict]]
AfterHook = Callable[[str, dict, dict], Optional[dict]]


@dataclass
class HookManager:
    before: list[BeforeHook] = field(default_factory=list)
    after: list[AfterHook] = field(default_factory=list)

    def add_before(self, fn: BeforeHook) -> None:
        self.before.append(fn)

    def add_after(self, fn: AfterHook) -> None:
        self.after.append(fn)

    def run_before(self, name: str, args: dict) -> tuple[dict, Optional[dict]]:
        """Returns (possibly-mutated args, optional override result).

        If a hook raises, returns ({}, {"error": str(exc)}) so the agent
        sees the denial as a structured tool result.
        """
        current = args
        for fn in self.before:
            try:
                out = fn(name, current)
            except Exception as e:
                return {}, {"error": f"hook denied {name}: {e}"}
            if out is not None:
                current = out
        return current, None

    def run_after(self, name: str, args: dict, result: dict) -> dict:
        current = result
        for fn in self.after:
            try:
                out = fn(name, args, current)
            except Exception as e:
                return {"error": f"after-hook for {name} raised: {e}", "original": current}
            if out is not None:
                current = out
        return current


def load_user_hooks(path: Optional[Path] = None) -> HookManager:
    """Import ~/.vibe/hooks.py if present and register its before/after_tool."""
    mgr = HookManager()
    p = path or HOOKS_PATH
    if not p.exists():
        return mgr
    spec = importlib.util.spec_from_file_location("vibe_user_hooks", p)
    if not spec or not spec.loader:  # pragma: no cover
        return mgr
    module = importlib.util.module_from_spec(spec)
    sys.modules["vibe_user_hooks"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:  # pragma: no cover
        sys.stderr.write(f"[vibe] failed to load {p}: {e}\n")
        return mgr
    if hasattr(module, "before_tool"):
        mgr.add_before(module.before_tool)
    if hasattr(module, "after_tool"):
        mgr.add_after(module.after_tool)
    return mgr
