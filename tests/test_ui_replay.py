import io

from rich.console import Console

from vibeharness.ui import TerminalUI


def _ui():
    buf = io.StringIO()
    return TerminalUI(Console(file=buf, force_terminal=False, width=100)), buf


def test_replay_renders_anthropic_history():
    ui, buf = _ui()
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "hi there"},
            {"type": "tool_use", "name": "list_dir", "input": {"path": "/tmp"}},
        ]},
        {"role": "user", "content": [{"type": "tool_result",
            "content": [{"type": "text", "text": "a.txt"}]}]},
        {"role": "assistant", "content": [{"type": "text", "text": "all done"}]},
    ]
    ui.replay(msgs)
    out = buf.getvalue()
    assert "hello" in out
    assert "hi there" in out
    assert "list_dir" in out
    assert "all done" in out
    assert "conversation so far" in out


def test_replay_skips_max_tokens_continuation_nudge():
    ui, buf = _ui()
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "real question"}]},
        {"role": "user", "content": [{"type": "text",
            "text": "Your previous response was cut off at the output token limit. Please continue from where you left off."}]},
    ]
    ui.replay(msgs)
    out = buf.getvalue()
    assert "real question" in out
    assert "previous response was cut off" not in out


def test_replay_handles_openai_format():
    ui, buf = _ui()
    msgs = [
        {"role": "user", "content": "what's up"},
        {"role": "assistant", "content": "checking",
         "tool_calls": [{"function": {"name": "grep", "arguments": '{"pattern":"foo"}'}}]},
        {"role": "tool", "content": "no matches"},
    ]
    ui.replay(msgs)
    out = buf.getvalue()
    assert "what's up" in out
    assert "checking" in out
    assert "grep" in out
    assert "no matches" in out


def test_replay_empty_messages_is_noop():
    ui, buf = _ui()
    ui.replay([])
    assert buf.getvalue() == ""


def test_thinking_spinner_lifecycle_no_crash():
    ui, _ = _ui()
    ui.thinking("loading")
    ui.done_thinking()
    ui.done_thinking()  # idempotent
