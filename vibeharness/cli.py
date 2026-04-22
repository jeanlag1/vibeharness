"""vibeharness CLI — `vibe`."""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

import typer

from . import __version__, config as cfg_mod
from .agent import Agent, AgentHooks
from .context import ContextManager
from .hooks import load_user_hooks
from .llm import make_provider
from .permissions import PermissionPolicy
from .prompts import build_system_prompt
from .repl_input import list_slash_commands, preprocess
from .session import SessionMeta, list_sessions, load_session, save_session
from .ui import TerminalUI

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help="vibeharness — a terminal coding agent.",
)


def _build_agent(
    ui: TerminalUI,
    provider_name: str,
    model: Optional[str],
    permission_mode: str,
    max_iters: int,
) -> Agent:
    provider = make_provider(provider_name, model=model)

    perms = PermissionPolicy(
        mode=permission_mode,
        prompter=lambda name, args: ui.ask_permission(name, args),
    )
    agent = Agent(
        provider=provider,
        permissions=perms,
        max_iters=max_iters,
        hooks=AgentHooks(
            on_text_delta=ui.text_delta,
            on_tool_start=ui.tool_start,
            on_tool_end=ui.tool_end,
            on_turn_end=lambda _t: ui.end_stream(),
        ),
    )
    # Wire up planning tools (one AgentPlan per session).
    from .planning import AgentPlan, make_plan_tools
    plan = AgentPlan()
    for t in make_plan_tools(plan):
        agent.tools[t.name] = t
    agent.plan = plan  # type: ignore[attr-defined]

    # Wire up the task (sub-agent) tool.
    from .subagent import make_task_tool
    agent.tools["task"] = make_task_tool(provider, parent_tools=dict(agent.tools))

    # Load user hooks from ~/.vibe/hooks.py
    agent.hook_manager = load_user_hooks()

    return agent


def _maybe_compact(agent: Agent, ctx: ContextManager, ui: TerminalUI) -> None:
    if ctx.needs_compaction(agent.messages):
        ui.divider("compacting context")
        agent.messages = ctx.compact(agent.provider, agent.messages)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM provider: anthropic|openai"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model id."),
    permission_mode: Optional[str] = typer.Option(None, "--permissions", help="auto | ask | deny"),
    auto: bool = typer.Option(False, "--auto", "-y", help="Shortcut for --permissions=auto."),
    resume: Optional[str] = typer.Option(None, "--resume", "-r", help="Resume a saved session id."),
    max_iters: int = typer.Option(50, "--max-iters", help="Max agent loop iterations per turn."),
    version: bool = typer.Option(False, "--version", help="Print version and exit."),
):
    """Run `vibe` with no subcommand to start the REPL, or `vibe run "<task>"` for one-shot."""
    if ctx.invoked_subcommand is not None:
        # Stash shared options for subcommands.
        ctx.obj = {
            "provider": provider, "model": model,
            "permission_mode": permission_mode, "auto": auto,
            "resume": resume, "max_iters": max_iters,
        }
        return
    if version:
        typer.echo(f"vibeharness {__version__}")
        raise typer.Exit(0)
    _start_session(provider=provider, model=model, permission_mode=permission_mode,
                   auto=auto, resume=resume, max_iters=max_iters, task=None)


@app.command("run")
def cmd_run(
    ctx: typer.Context,
    task: str = typer.Argument(..., help="Task for the agent."),
):
    """One-shot: run a single task and exit."""
    o = ctx.obj or {}
    _start_session(
        provider=o.get("provider"), model=o.get("model"),
        permission_mode=o.get("permission_mode"), auto=o.get("auto", False),
        resume=o.get("resume"), max_iters=o.get("max_iters", 50),
        task=task,
    )


def _start_session(
    provider: Optional[str], model: Optional[str], permission_mode: Optional[str],
    auto: bool, resume: Optional[str], max_iters: int, task: Optional[str],
) -> None:
    cfg = cfg_mod.load()
    provider = provider or cfg.provider
    model = model or cfg.model
    permission_mode = "auto" if auto else (permission_mode or cfg.permission_mode)

    ui = TerminalUI()
    if provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        ui.console.print("[red]ANTHROPIC_API_KEY is not set.[/red]")
        raise typer.Exit(1)
    if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        ui.console.print("[red]OPENAI_API_KEY is not set.[/red]")
        raise typer.Exit(1)

    agent = _build_agent(ui, provider, model, permission_mode, max_iters)
    context = ContextManager(max_tokens=cfg.max_context_tokens)

    session_id = resume or uuid.uuid4().hex[:10]
    if resume:
        data = load_session(resume)
        if not data:
            ui.console.print(f"[red]no session: {resume}[/red]")
            raise typer.Exit(1)
        agent.messages = data["messages"]
        agent.total_input_tokens = data.get("tokens", {}).get("input", 0)
        agent.total_output_tokens = data.get("tokens", {}).get("output", 0)
        ui.console.print(f"[dim]resumed session {resume} ({len(agent.messages)} messages)[/dim]")

    meta = SessionMeta(
        id=session_id,
        created_at=time.time(),
        provider=provider,
        model=agent.provider.model,
        cwd=os.getcwd(),
    )
    ui.banner(agent.provider.model, os.getcwd())

    def _save():
        return save_session(session_id, meta, agent.messages, agent.total_input_tokens, agent.total_output_tokens)

    # Mid-turn checkpoint: write the session after every tool round.
    agent.on_checkpoint = _save

    try:
        if task:
            _run_one(agent, task, ui, context)
            _save()
            return
        # REPL
        while True:
            try:
                user_input = ui.user_prompt().strip()
            except (EOFError, KeyboardInterrupt):
                ui.console.print("\n[dim]bye.[/dim]")
                break
            if not user_input:
                continue
            if user_input in {"/exit", "/quit"}:
                break
            if user_input == "/save":
                p = _save()
                ui.console.print(f"[dim]saved → {p}[/dim]")
                continue
            if user_input == "/clear":
                agent.messages.clear()
                ui.console.print("[dim]history cleared[/dim]")
                continue
            if user_input.startswith("/compact"):
                ui.divider("compacting")
                agent.messages = context.compact(agent.provider, agent.messages)
                continue
            if user_input == "/help":
                cmds = list_slash_commands()
                cmd_str = "  ".join(f"/{c}" for c in cmds) if cmds else "(none defined)"
                ui.console.print("[dim]builtin: /save /clear /compact /help /exit[/dim]")
                ui.console.print(f"[dim]custom: {cmd_str}[/dim]")
                ui.console.print("[dim]use @path/to/file in any message to attach file content[/dim]")
                continue
            try:
                expanded = preprocess(user_input)
                _run_one(agent, expanded, ui, context)
                _save()
            except KeyboardInterrupt:
                ui.console.print("\n[yellow]interrupted[/yellow]")
                continue
    finally:
        try:
            from .tools.bash import get_manager
            get_manager().shutdown()
        except Exception:
            pass


def _run_one(agent: Agent, task: str, ui: TerminalUI, context: ContextManager) -> None:
    from .pricing import estimate_cost
    _maybe_compact(agent, context, ui)
    agent.run(task)
    cost = estimate_cost(
        agent.provider.model,
        agent.total_input_tokens,
        agent.total_output_tokens,
        agent.total_cache_read_tokens,
        agent.total_cache_write_tokens,
    )
    ui.usage(
        agent.total_input_tokens, agent.total_output_tokens,
        agent.total_cache_read_tokens, agent.total_cache_write_tokens,
        cost_usd=cost, model=agent.provider.model,
    )


@app.command("sessions")
def cmd_sessions():
    """List saved sessions."""
    rows = list_sessions()
    if not rows:
        typer.echo("(no sessions)")
        return
    for r in rows:
        typer.echo(f"  {r['id']:12}  msgs={r['messages']:<3}  model={r.get('model','?')}  cwd={r.get('cwd','?')}")


@app.command("tools")
def cmd_tools():
    """List available tools."""
    from .tools import build_default_registry
    for name, t in build_default_registry().items():
        marker = "✎" if t.mutating else " "
        typer.echo(f"  {marker} {name:18}  {t.description.splitlines()[0]}")


if __name__ == "__main__":
    app()
