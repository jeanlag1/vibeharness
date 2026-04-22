"""Tests for the agent loop using a fake provider (no API key needed)."""
from __future__ import annotations

import pytest

from vibeharness.agent import Agent, AgentHooks
from vibeharness.llm import AssistantTurn, ToolCall
from vibeharness.permissions import PermissionPolicy
from vibeharness.tools import build_default_registry


class FakeProvider:
    """Plays back a scripted list of AssistantTurns."""

    name = "fake"
    model = "fake-1"

    def __init__(self, script: list[AssistantTurn]):
        self.script = list(script)
        self.calls: list[dict] = []

    def complete(self, system, messages, tools, max_tokens=4096, on_text_delta=None):
        self.calls.append({"messages": list(messages), "n_tools": len(tools)})
        if not self.script:
            return AssistantTurn(text="(done)", stop_reason="end_turn")
        return self.script.pop(0)


def test_agent_runs_until_no_tool_calls(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    file_path = str(tmp_path / "out.txt")
    script = [
        AssistantTurn(
            tool_calls=[ToolCall(id="c1", name="write_file", args={"path": file_path, "content": "hi"})],
            stop_reason="tool_use",
        ),
        AssistantTurn(
            tool_calls=[ToolCall(id="c2", name="read_file", args={"path": file_path})],
            stop_reason="tool_use",
        ),
        AssistantTurn(text="all done", stop_reason="end_turn"),
    ]
    provider = FakeProvider(script)
    agent = Agent(
        provider=provider,
        tools=build_default_registry(),
        permissions=PermissionPolicy(mode="auto"),
    )
    final = agent.run("do the thing")
    assert "all done" in final.text
    assert (tmp_path / "out.txt").read_text() == "hi"
    assert len(provider.calls) == 3


def test_permissions_deny_blocks_mutating_tool(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = [
        AssistantTurn(
            tool_calls=[ToolCall(id="c1", name="write_file", args={"path": "x.txt", "content": "no"})],
            stop_reason="tool_use",
        ),
        AssistantTurn(text="ok denied", stop_reason="end_turn"),
    ]
    captured: list[dict] = []

    def on_tool_end(tc, payload):
        captured.append(payload)

    agent = Agent(
        provider=FakeProvider(script),
        permissions=PermissionPolicy(mode="deny"),
        hooks=AgentHooks(on_tool_end=on_tool_end),
    )
    agent.run("try to write")
    assert not (tmp_path / "x.txt").exists()
    assert "denied" in captured[0]["error"]


def test_hooks_fire(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = [
        AssistantTurn(
            text="thinking",
            tool_calls=[ToolCall(id="c1", name="list_dir", args={"path": str(tmp_path)})],
        ),
        AssistantTurn(text="done"),
    ]
    seen = {"text": [], "starts": [], "ends": []}
    agent = Agent(
        provider=FakeProvider(script),
        permissions=PermissionPolicy(mode="auto"),
        hooks=AgentHooks(
            on_assistant_text=lambda t: seen["text"].append(t),
            on_tool_start=lambda tc: seen["starts"].append(tc.name),
            on_tool_end=lambda tc, r: seen["ends"].append((tc.name, "error" not in r)),
        ),
    )
    agent.run("hi")
    assert "thinking" in seen["text"]
    assert seen["starts"] == ["list_dir"]
    assert seen["ends"] == [("list_dir", True)]


def test_iteration_cap(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    # Provider that always asks for another tool call.
    class Loop:
        name = "fake"; model = "x"
        def complete(self, system, messages, tools, max_tokens=4096, on_text_delta=None):
            return AssistantTurn(
                tool_calls=[ToolCall(id="c", name="list_dir", args={"path": str(tmp_path)})],
            )
    agent = Agent(provider=Loop(), permissions=PermissionPolicy(mode="auto"), max_iters=3)
    agent.run("loop forever")
    # Should have appended exactly max_iters assistant messages + corresponding tool results.
    assistant_msgs = [m for m in agent.messages if m.get("role") == "assistant"]
    assert len(assistant_msgs) == 3
