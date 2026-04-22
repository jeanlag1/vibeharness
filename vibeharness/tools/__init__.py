"""Tool registry: turn Python functions into LLM-callable tools.

Each tool is described with a name, description, JSON schema, and a callable.
Schemas are hand-written (more reliable than introspecting type hints for
non-trivial parameters).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from . import bash as bash_tool
from . import files as file_tool


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    func: Callable[..., dict]
    mutating: bool = False

    def to_anthropic(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


def _str(desc: str) -> dict:
    return {"type": "string", "description": desc}


def _int(desc: str) -> dict:
    return {"type": "integer", "description": desc}


def build_default_registry() -> dict[str, Tool]:
    tools: list[Tool] = [
        Tool(
            name="read_file",
            description="Read a UTF-8 text file. Supports offset/limit (in lines) for large files.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": _str("Path to file (absolute or relative to cwd)."),
                    "offset": _int("Line offset to start at (0-indexed). Optional."),
                    "limit": _int("Max number of lines to read. Optional."),
                },
                "required": ["path"],
            },
            func=lambda **kw: file_tool.read_file(**kw),
        ),
        Tool(
            name="write_file",
            description="Create or overwrite a file with the given content. Parent dirs created automatically.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": _str("Path to file."),
                    "content": _str("Full file content."),
                },
                "required": ["path", "content"],
            },
            func=lambda **kw: file_tool.write_file(**kw),
            mutating=True,
        ),
        Tool(
            name="edit_file",
            description=(
                "Replace exact occurrences of `old` with `new` in a file. "
                "Fails if the match count differs from `count` (default 1). "
                "Pass count=-1 to replace all. Provide enough surrounding "
                "context in `old` to make the match unique."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": _str("Path to file."),
                    "old": _str("Exact substring to replace (include enough context to be unique)."),
                    "new": _str("Replacement string."),
                    "count": _int("Expected number of matches (default 1, -1 for all)."),
                },
                "required": ["path", "old", "new"],
            },
            func=lambda **kw: file_tool.edit_file(**kw),
            mutating=True,
        ),
        Tool(
            name="grep",
            description="Recursively search for a regex pattern. Skips .git, node_modules, etc.",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": _str("Python regex pattern."),
                    "path": _str("Directory or file to search (default: cwd)."),
                    "glob": _str("Optional filename glob, e.g. '*.py'."),
                    "ignore_case": {"type": "boolean", "description": "Case-insensitive match."},
                },
                "required": ["pattern"],
            },
            func=lambda **kw: file_tool.grep(**kw),
        ),
        Tool(
            name="glob_files",
            description="Find files matching a glob pattern (supports ** for recursive).",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": _str("Glob pattern, e.g. 'src/**/*.py'."),
                    "path": _str("Root directory (default: cwd)."),
                },
                "required": ["pattern"],
            },
            func=lambda **kw: file_tool.glob_files(**kw),
        ),
        Tool(
            name="list_dir",
            description="List entries in a directory. Directories are suffixed with /.",
            input_schema={
                "type": "object",
                "properties": {"path": _str("Directory path (default: cwd).")},
                "required": [],
            },
            func=lambda **kw: file_tool.list_dir(**(kw or {"path": "."})),
        ),
        Tool(
            name="bash",
            description=(
                "Run a shell command in a persistent bash session. State (env, cwd) "
                "persists across calls with the same session_id. Returns stdout, "
                "exit_code, and timed_out flag."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "command": _str("Shell command to execute."),
                    "session_id": _str("Session id for state persistence (default 'default')."),
                    "timeout": _int("Timeout in seconds (default 120)."),
                },
                "required": ["command"],
            },
            func=lambda **kw: bash_tool.run_bash(**kw),
            mutating=True,
        ),
        Tool(
            name="bash_background",
            description="Start a long-running command in the background. Returns a bg_id.",
            input_schema={
                "type": "object",
                "properties": {"command": _str("Shell command to run in background.")},
                "required": ["command"],
            },
            func=lambda **kw: bash_tool.run_bash_background(**kw),
            mutating=True,
        ),
        Tool(
            name="bash_read",
            description="Read accumulated output from a background process.",
            input_schema={
                "type": "object",
                "properties": {
                    "bg_id": _str("Background process id."),
                    "tail": _int("Bytes from end of log (default 4000)."),
                },
                "required": ["bg_id"],
            },
            func=lambda **kw: bash_tool.read_bash_background(**kw),
        ),
        Tool(
            name="bash_stop",
            description="Stop a background process started with bash_background.",
            input_schema={
                "type": "object",
                "properties": {"bg_id": _str("Background process id.")},
                "required": ["bg_id"],
            },
            func=lambda **kw: bash_tool.stop_bash_background(**kw),
            mutating=True,
        ),
    ]
    return {t.name: t for t in tools}


def dispatch(registry: dict[str, Tool], name: str, args: dict[str, Any]) -> dict:
    if name not in registry:
        return {"error": f"unknown tool: {name}"}
    tool = registry[name]
    try:
        return tool.func(**args)
    except (file_tool.ToolError, bash_tool.ToolError) as e:
        return {"error": str(e)}
    except TypeError as e:
        return {"error": f"bad arguments to {name}: {e}"}
    except Exception as e:  # pragma: no cover
        return {"error": f"{type(e).__name__}: {e}"}
