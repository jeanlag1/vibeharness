import json
from pathlib import Path

from vibeharness.context import ContextManager, count_tokens_text, count_tokens_messages
from vibeharness.session import SessionMeta, load_session, save_session, session_path


def test_count_tokens_text():
    assert count_tokens_text("hello world") > 0


def test_count_tokens_messages():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "hello there"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]},
    ]
    assert count_tokens_messages(msgs) > 0


def test_compaction_threshold():
    ctx = ContextManager(max_tokens=100, compact_threshold=0.5)
    big = [{"role": "user", "content": "x " * 500}]
    assert ctx.needs_compaction(big) is True
    small = [{"role": "user", "content": "hi"}]
    assert ctx.needs_compaction(small) is False


def test_compaction_calls_provider_and_keeps_tail():
    class Stub:
        name = "fake"; model = "x"
        called = False
        def complete(self, system, messages, tools, max_tokens=4096, on_text_delta=None):
            Stub.called = True
            from vibeharness.llm import AssistantTurn
            return AssistantTurn(text="SUMMARY")
    ctx = ContextManager(max_tokens=100, keep_recent=2)
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(8)]
    out = ctx.compact(Stub(), msgs)
    assert Stub.called
    assert len(out) == 3  # primer + 2 tail
    # primer mentions SUMMARY
    flat = json.dumps(out[0])
    assert "SUMMARY" in flat


def test_session_save_load(tmp_path, monkeypatch):
    monkeypatch.setattr("vibeharness.session.DEFAULT_SESSION_DIR", tmp_path)
    meta = SessionMeta(id="s1", created_at=0.0, provider="fake", model="x", cwd="/tmp")
    save_session("s1", meta, [{"role": "user", "content": "hi"}], 10, 5)
    data = load_session("s1")
    assert data is not None
    assert data["meta"]["id"] == "s1"
    assert data["tokens"]["input"] == 10
    assert load_session("nope") is None
