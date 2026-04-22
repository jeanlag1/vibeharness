"""File tools: read, write, edit, grep, glob.

These are pure-Python helpers that return structured dicts. The agent layer
turns them into LLM tool calls; tests can call them directly.
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Optional

MAX_READ_BYTES = 200_000  # ~50k tokens worst case
MAX_GREP_HITS = 200


class ToolError(Exception):
    """Raised on user-visible tool failures (caught by agent loop)."""


def _resolve(path: str, root: Optional[Path] = None) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = (root or Path.cwd()) / p
    return p.resolve()


def read_file(path: str, offset: int = 0, limit: Optional[int] = None) -> dict:
    """Read a UTF-8 text file. Returns {content, total_lines, truncated}."""
    p = _resolve(path)
    if not p.exists():
        raise ToolError(f"file not found: {path}")
    if not p.is_file():
        raise ToolError(f"not a regular file: {path}")
    data = p.read_bytes()
    if len(data) > MAX_READ_BYTES and limit is None:
        text = data[:MAX_READ_BYTES].decode("utf-8", errors="replace")
        return {
            "content": text,
            "total_lines": text.count("\n") + 1,
            "truncated": True,
            "note": f"file is {len(data)} bytes; first {MAX_READ_BYTES} returned. Use offset/limit.",
        }
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    total = len(lines)
    if offset or limit is not None:
        end = offset + limit if limit is not None else total
        lines = lines[offset:end]
    return {
        "content": "".join(lines),
        "total_lines": total,
        "truncated": False,
    }


def write_file(path: str, content: str, create_dirs: bool = True) -> dict:
    """Write content to a file (overwrites). Returns {bytes_written, created}."""
    p = _resolve(path)
    created = not p.exists()
    if create_dirs:
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"bytes_written": len(content.encode("utf-8")), "created": created, "path": str(p)}


def edit_file(path: str, old: str, new: str, count: int = 1) -> dict:
    """Replace exactly `count` occurrences of `old` with `new`.

    Fails loudly if the match count differs — same semantics as Claude Code's
    Edit tool. Use count=-1 to replace all occurrences.
    """
    p = _resolve(path)
    if not p.exists():
        raise ToolError(f"file not found: {path}")
    text = p.read_text(encoding="utf-8")
    occurrences = text.count(old)
    if occurrences == 0:
        raise ToolError("`old` string not found in file")
    if count != -1 and occurrences != count:
        raise ToolError(
            f"expected {count} occurrence(s) of `old`; found {occurrences}. "
            "Add more context to make the match unique."
        )
    new_text = text.replace(old, new, occurrences if count == -1 else count)
    p.write_text(new_text, encoding="utf-8")
    return {"replacements": occurrences if count == -1 else count, "path": str(p)}


def grep(
    pattern: str,
    path: str = ".",
    glob: Optional[str] = None,
    ignore_case: bool = False,
    max_results: int = MAX_GREP_HITS,
) -> dict:
    """Recursively search for a regex pattern. Returns {matches: [{file,line,text}], truncated}."""
    root = _resolve(path)
    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as e:
        raise ToolError(f"invalid regex: {e}")

    matches: list[dict] = []
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}

    def iter_files():
        if root.is_file():
            yield root
            return
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs and not d.startswith(".")]
            for fn in filenames:
                if glob and not fnmatch.fnmatch(fn, glob):
                    continue
                yield Path(dirpath) / fn

    for fp in iter_files():
        try:
            with fp.open("r", encoding="utf-8", errors="ignore") as f:
                for i, line in enumerate(f, 1):
                    if regex.search(line):
                        matches.append({"file": str(fp), "line": i, "text": line.rstrip("\n")})
                        if len(matches) >= max_results:
                            return {"matches": matches, "truncated": True}
        except (OSError, UnicodeDecodeError):
            continue
    return {"matches": matches, "truncated": False}


def glob_files(pattern: str, path: str = ".") -> dict:
    """Glob for files matching `pattern` (supports ** for recursive)."""
    root = _resolve(path)
    if not root.exists():
        raise ToolError(f"path not found: {path}")
    results = sorted(str(p) for p in root.glob(pattern) if p.is_file())
    return {"files": results, "count": len(results)}


def list_dir(path: str = ".") -> dict:
    """List entries in a directory, marking dirs with trailing /."""
    p = _resolve(path)
    if not p.exists():
        raise ToolError(f"path not found: {path}")
    if not p.is_dir():
        raise ToolError(f"not a directory: {path}")
    entries = []
    for entry in sorted(p.iterdir()):
        name = entry.name + ("/" if entry.is_dir() else "")
        entries.append(name)
    return {"path": str(p), "entries": entries}
