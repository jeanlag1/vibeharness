"""Test that the agent forwards on_text_delta to the provider."""
from vibeharness.agent import Agent, AgentHooks
from vibeharness.llm import AssistantTurn, ToolCall
from vibeharness.permissions import PermissionPolicy


class StreamingProvider:
    name = "fake"; model = "x"
    def complete(self, system, messages, tools, max_tokens=4096, on_text_delta=None):
        if on_text_delta is not None:
            for token in ["hello ", "world", "!"]:
                on_text_delta(token)
        return AssistantTurn(text="hello world!", stop_reason="end_turn")


def test_streaming_deltas_forwarded():
    chunks: list[str] = []
    agent = Agent(
        provider=StreamingProvider(),
        permissions=PermissionPolicy(mode="auto"),
        hooks=AgentHooks(on_text_delta=lambda t: chunks.append(t)),
    )
    agent.run("stream please")
    assert chunks == ["hello ", "world", "!"]


def test_no_double_text_when_streaming():
    """If on_text_delta is set, on_assistant_text should NOT also fire."""
    full: list[str] = []
    chunks: list[str] = []
    agent = Agent(
        provider=StreamingProvider(),
        permissions=PermissionPolicy(mode="auto"),
        hooks=AgentHooks(
            on_text_delta=lambda t: chunks.append(t),
            on_assistant_text=lambda t: full.append(t),
        ),
    )
    agent.run("hi")
    assert chunks  # got deltas
    assert full == []  # full text suppressed
