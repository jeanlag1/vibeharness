"""Input preprocessing for the REPL.

Two features:

- `@path/to/file` mentions: scan user input for tokens starting with @,
  resolve them as file paths, and append the file content as additional
  user-message context. The original @ token stays in place so the model
  knows which file was referenced.

- `/cmd args...` slash commands: load `~/.vibe/commands/<cmd>.md` and use
  its content as the prompt. The remainder of the line is appended after
  a separator so commands can take free-form arguments.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .tools.files import MAX_READ_BYTES

COMMANDS_DIR = Path.home() / ".vibe" / "commands"
_MENTION_RE = re.compile(r"(?<!\S)@([^\s@][^\s]*)")


def _resolve_mention(token: str, cwd: Path) -> Optional[Path]:
    p = Path(token).expanduser()
    if not p.is_absolute():
        p = cwd / p
    return p if p.is_file() else None


def expand_mentions(text: str, cwd: Optional[Path] = None, max_bytes: int = 50_000) -> str:
    """Return text with file content appended for any @path mentions.

    Original `@path` tokens stay intact; a 'Referenced files:' section is
    appended below the user's message.
    """
    cwd = cwd or Path.cwd()
    seen: list[Path] = []
    for m in _MENTION_RE.finditer(text):
        path = _resolve_mention(m.group(1), cwd)
        if path and path not in seen:
            seen.append(path)
    if not seen:
        return text

    parts = [text, "", "---", "Referenced files:"]
    for p in seen:
        try:
            data = p.read_bytes()
        except OSError as e:
            parts.append(f"\n## {p}\n[error reading: {e}]")
            continue
        truncated = ""
        if len(data) > max_bytes:
            data = data[:max_bytes]
            truncated = f"\n[...file truncated, original {p.stat().st_size} bytes...]"
        try:
            content = data.decode("utf-8", errors="replace")
        except Exception:
            content = "[binary file]"
        parts.append(f"\n## {p}\n```\n{content}{truncated}\n```")
    return "\n".join(parts)


def expand_slash_command(text: str, commands_dir: Optional[Path] = None) -> str:
    """If text starts with /name, replace with ~/.vibe/commands/name.md content.

    The rest of the line (after `/name `) is appended after a separator so
    slash commands can take free-form arguments.
    """
    if not text.startswith("/"):
        return text
    head, _, rest = text[1:].partition(" ")
    if not head:
        return text
    cmds = commands_dir or COMMANDS_DIR
    path = cmds / f"{head}.md"
    if not path.exists():
        return text
    body = path.read_text(encoding="utf-8").strip()
    if rest.strip():
        return f"{body}\n\n---\nArguments: {rest.strip()}"
    return body


def list_slash_commands(commands_dir: Optional[Path] = None) -> list[str]:
    cmds = commands_dir or COMMANDS_DIR
    if not cmds.exists():
        return []
    return sorted(p.stem for p in cmds.glob("*.md"))


def preprocess(text: str, commands_dir: Optional[Path] = None,
               cwd: Optional[Path] = None) -> str:
    """Apply slash-command expansion then @file mention expansion."""
    text = expand_slash_command(text, commands_dir=commands_dir)
    text = expand_mentions(text, cwd=cwd)
    return text
