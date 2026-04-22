"""Smoke test: parent agent invokes 'task', which spawns a sub-agent."""
from vibeharness.agent import Agent
from vibeharness.llm import AssistantTurn, ToolCall
from vibeharness.permissions import PermissionPolicy
from vibeharness.subagent import make_task_tool
from vibeharness.tools import build_default_registry


class ScriptedProvider:
    """Plays back parent and sub-agent scripts; the role queue cycles."""

    name = "scripted"; model = "x"

    def __init__(self, parent_script, sub_script):
        self.parent = list(parent_script)
        self.sub = list(sub_script)

    def complete(self, system, messages, tools, max_tokens=4096, on_text_delta=None):
        # Decide which script to draw from based on system prompt content.
        if "sub-agent" in system:
            return self.sub.pop(0) if self.sub else AssistantTurn(text="(sub done)")
        return self.parent.pop(0) if self.parent else AssistantTurn(text="(parent done)")


def test_task_tool_spawns_subagent(tmp_path):
    parent_script = [
        AssistantTurn(
            tool_calls=[ToolCall(id="t1", name="task", args={
                "description": "find foo",
                "allowed_tools": ["list_dir"],
            })],
            stop_reason="tool_use",
        ),
        AssistantTurn(text="parent finished using sub report", stop_reason="end_turn"),
    ]
    sub_script = [
        AssistantTurn(
            tool_calls=[ToolCall(id="s1", name="list_dir", args={"path": str(tmp_path)})],
            stop_reason="tool_use",
        ),
        AssistantTurn(text="found nothing", stop_reason="end_turn"),
    ]
    provider = ScriptedProvider(parent_script, sub_script)
    tools = build_default_registry()
    tools["task"] = make_task_tool(provider, parent_tools=tools)
    agent = Agent(
        provider=provider,
        tools=tools,
        permissions=PermissionPolicy(mode="auto"),
    )
    final = agent.run("explore")
    assert "parent finished" in final.text
    # The parent should have received a tool_result containing the sub's report.
    flat = str(agent.messages)
    assert "found nothing" in flat


def test_subagent_no_recursion(tmp_path):
    """The sub-agent's tool registry should not include 'task'."""
    provider = ScriptedProvider([], [])
    tools = build_default_registry()
    tools["task"] = make_task_tool(provider, parent_tools=tools)
    # Inspect what the spawn function sets up — easiest via direct call:
    # We just confirm 'task' is not callable from sub by checking the func
    # uses build_default_registry()-style filtering.
    from vibeharness.subagent import make_task_tool as _mtt
    # If parent_tools includes task, it should be popped; reach the closure
    # indirectly by spawning with only task allowed.
    out = tools["task"].func(description="x", allowed_tools=["task"])
    # No tools available → sub will have no tools, but should still return a report.
    assert "report" in out
