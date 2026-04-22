"""Terminal UI built on Rich.

Renders assistant text, tool calls (with arg previews), tool results
(with diff/output panels), and an approval prompt.
"""
from __future__ import annotations

import difflib
import json
import os
from typing import Optional

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text

from .llm import ToolCall


class TerminalUI:
    def __init__(self, console: Optional[Console] = None) -> None:
        self.console = console or Console()
        self._last_was_text = False
        self._streaming = False

    # ----------------------------------------------------- streaming text
    def text_delta(self, delta: str) -> None:
        if not self._streaming:
            self.console.print()  # leading newline once per turn
            self._streaming = True
        self.console.print(delta, end="", soft_wrap=True, highlight=False, markup=False)

    def end_stream(self) -> None:
        if self._streaming:
            self.console.print()
            self._streaming = False

    # ------------------------------------------------------- assistant text
    def assistant_text(self, text: str) -> None:
        if not text.strip():
            return
        self.console.print()
        self.console.print(Markdown(text))
        self._last_was_text = True

    # -------------------------------------------------------- tool render
    def tool_start(self, tc: ToolCall) -> None:
        self.end_stream()
        title = f"[bold cyan]▸ {tc.name}[/bold cyan]"
        preview = self._args_preview(tc.name, tc.args)
        self.console.print(f"{title} [dim]{preview}[/dim]")

    def tool_end(self, tc: ToolCall, result: dict) -> None:
        if "error" in result:
            self.console.print(
                Panel(
                    Text(str(result["error"]), style="red"),
                    title=f"× {tc.name}",
                    title_align="left",
                    border_style="red",
                    expand=False,
                )
            )
            return

        body = self._render_result(tc, result)
        if body is not None:
            self.console.print(body)

    # -------------------------------------------------------- approval
    def ask_permission(self, tool_name: str, args: dict) -> str:
        self.console.print(
            Panel(
                Text(f"{tool_name}({_short_args(args)})", style="yellow"),
                title="permission required",
                border_style="yellow",
                expand=False,
            )
        )
        choice = Prompt.ask(
            "[yellow]Allow?[/yellow]",
            choices=["y", "a", "n"],
            default="y",
            show_choices=True,
        )
        return {"y": "allow", "a": "allow_always", "n": "deny"}[choice]

    # -------------------------------------------------------- session
    def banner(self, model: str, cwd: str) -> None:
        self.console.print(
            Panel(
                Text.from_markup(
                    f"[bold]vibeharness[/bold] · model: [cyan]{model}[/cyan] · cwd: [dim]{cwd}[/dim]\n"
                    "Type your task. [dim]Ctrl-C to exit.[/dim]"
                ),
                border_style="magenta",
                expand=False,
            )
        )

    def user_prompt(self) -> str:
        return Prompt.ask("\n[bold green]you[/bold green]")

    def divider(self, label: str = "") -> None:
        self.console.print(Rule(label, style="dim"))

    def usage(self, in_tokens: int, out_tokens: int,
              cache_read: int = 0, cache_write: int = 0,
              cost_usd: float | None = None, model: str = "") -> None:
        from .pricing import format_cost
        cache_str = f" cache_r={cache_read} cache_w={cache_write}" if (cache_read or cache_write) else ""
        cost_str = f"  cost≈{format_cost(cost_usd)}" if cost_usd is not None else ""
        self.console.print(
            f"[dim]tokens: in={in_tokens} out={out_tokens}{cache_str}{cost_str}[/dim]",
            justify="right",
        )

    # --------------------------------------------------------- internals
    def _args_preview(self, name: str, args: dict) -> str:
        if name in {"read_file", "write_file", "list_dir", "glob_files"}:
            return args.get("path") or args.get("pattern") or ""
        if name == "edit_file":
            return args.get("path", "")
        if name == "grep":
            return f"/{args.get('pattern','')}/ in {args.get('path', '.')}"
        if name in {"bash", "bash_background"}:
            cmd = args.get("command", "")
            return cmd if len(cmd) < 80 else cmd[:77] + "..."
        if name in {"bash_read", "bash_stop"}:
            return args.get("bg_id", "")
        return _short_args(args)

    def _render_result(self, tc: ToolCall, result: dict) -> Optional[Panel]:
        name = tc.name
        if name in {"set_plan", "update_plan_item", "get_plan"}:
            items = result.get("items", [])
            if not items:
                return Panel(Text("(empty plan)", style="dim"), border_style="dim", expand=False)
            icons = {"pending": "○", "in_progress": "◐", "done": "●", "blocked": "✕"}
            colors = {"pending": "white", "in_progress": "yellow", "done": "green", "blocked": "red"}
            lines = []
            for it in items:
                s = it["status"]
                lines.append(f"[{colors.get(s,'white')}]{icons.get(s,'?')} {it['text']}[/{colors.get(s,'white')}]")
            return Panel(
                Text.from_markup("\n".join(lines)),
                title=f"📋 plan · {result.get('summary','')}",
                title_align="left",
                border_style="magenta",
                expand=False,
            )
        if name == "read_file":
            content = result.get("content", "")
            n = content.count("\n")
            note = f" ({n}+ lines)" if n > 30 else ""
            return Panel(
                _truncated(content, 1500),
                title=f"📄 {tc.args.get('path','')}{note}",
                title_align="left",
                border_style="blue",
                expand=False,
            )
        if name == "write_file":
            return Panel(
                Text(f"wrote {result.get('bytes_written',0)} bytes" + (" (new file)" if result.get("created") else "")),
                title=f"✓ write {tc.args.get('path','')}",
                title_align="left",
                border_style="green",
                expand=False,
            )
        if name == "edit_file":
            diff = _make_diff(tc.args.get("old", ""), tc.args.get("new", ""))
            return Panel(
                diff,
                title=f"✎ edit {tc.args.get('path','')} ({result.get('replacements',0)})",
                title_align="left",
                border_style="green",
                expand=False,
            )
        if name == "grep":
            matches = result.get("matches", [])
            if not matches:
                return Panel(Text("no matches", style="dim"), border_style="dim", expand=False)
            lines = []
            for m in matches[:15]:
                lines.append(f"[dim]{_short(m['file'])}:{m['line']}[/dim]  {m['text'][:140]}")
            extra = f"\n[dim]…and {len(matches)-15} more[/dim]" if len(matches) > 15 else ""
            return Panel(
                Text.from_markup("\n".join(lines) + extra),
                title=f"🔎 {len(matches)} matches",
                title_align="left",
                border_style="blue",
                expand=False,
            )
        if name == "list_dir":
            entries = result.get("entries", [])
            return Panel(
                Text("  ".join(entries[:60]) + ("\n…" if len(entries) > 60 else "")),
                title=f"📁 {result.get('path','')}",
                title_align="left",
                border_style="blue",
                expand=False,
            )
        if name == "glob_files":
            files = result.get("files", [])
            return Panel(
                Text("\n".join(_short(f) for f in files[:40]) + (f"\n…and {len(files)-40} more" if len(files) > 40 else "")),
                title=f"🔎 {result.get('count',0)} files",
                title_align="left",
                border_style="blue",
                expand=False,
            )
        if name == "bash":
            stdout = result.get("stdout", "").rstrip()
            rc = result.get("exit_code")
            timed_out = result.get("timed_out")
            color = "green" if rc == 0 and not timed_out else "red"
            title = f"$ {tc.args.get('command','')[:80]}  [exit={rc}{' TIMEOUT' if timed_out else ''}]"
            return Panel(
                _truncated(stdout, 2000) or Text("(no output)", style="dim"),
                title=title,
                title_align="left",
                border_style=color,
                expand=False,
            )
        if name == "bash_background":
            return Panel(
                Text(f"started bg pid={result.get('pid')} bg_id={result.get('bg_id')}"),
                border_style="green", expand=False,
            )
        if name == "bash_read":
            status = "running" if result.get("running") else f"exited({result.get('exit_code')})"
            return Panel(
                _truncated(result.get("output", ""), 2000),
                title=f"bg {result.get('bg_id','')} {status}",
                title_align="left",
                border_style="blue", expand=False,
            )
        if name == "bash_stop":
            return Panel(Text(f"stopped (exit={result.get('exit_code')})"), border_style="green", expand=False)
        # Fallback
        return Panel(
            Text(_truncated(json.dumps(result, default=str, indent=2), 1500)),
            title=name,
            border_style="dim",
            expand=False,
        )


# ---------------------------------------------------------------- helpers
def _short(p: str) -> str:
    home = os.path.expanduser("~")
    if p.startswith(home):
        p = "~" + p[len(home):]
    return p


def _short_args(args: dict) -> str:
    s = json.dumps(args, default=str, ensure_ascii=False)
    return s if len(s) < 80 else s[:77] + "..."


def _truncated(s: str, n: int) -> Text:
    if len(s) <= n:
        return Text(s)
    return Text(s[: n // 2] + f"\n…[truncated {len(s)-n} chars]…\n" + s[-n // 2 :])


def _make_diff(old: str, new: str) -> Group:
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines, n=2, lineterm=""))
    if not diff:
        return Group(Text("(no textual change)", style="dim"))
    body_lines = []
    for line in diff[2:]:  # skip --- / +++
        if line.startswith("+"):
            body_lines.append(Text(line, style="green"))
        elif line.startswith("-"):
            body_lines.append(Text(line, style="red"))
        elif line.startswith("@@"):
            body_lines.append(Text(line, style="cyan"))
        else:
            body_lines.append(Text(line, style="dim"))
    return Group(*body_lines)
