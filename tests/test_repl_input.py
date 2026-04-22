from pathlib import Path

from vibeharness.repl_input import (
    expand_mentions,
    expand_slash_command,
    list_slash_commands,
    preprocess,
)


def test_mention_appends_file(tmp_path):
    p = tmp_path / "x.py"
    p.write_text("def foo(): pass\n")
    out = expand_mentions(f"check @{p}", cwd=tmp_path)
    assert "Referenced files" in out
    assert "def foo()" in out
    assert f"@{p}" in out  # original token preserved


def test_mention_relative(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    out = expand_mentions("look at @a.txt please", cwd=tmp_path)
    assert "hello" in out


def test_no_mention_returns_unchanged():
    assert expand_mentions("nothing here") == "nothing here"


def test_email_not_a_mention(tmp_path):
    # @ preceded by non-whitespace shouldn't trigger.
    out = expand_mentions("ping me at user@host", cwd=tmp_path)
    assert "Referenced files" not in out


def test_unknown_path_skipped(tmp_path):
    out = expand_mentions("see @/nope/missing.txt", cwd=tmp_path)
    assert "Referenced files" not in out


def test_truncate_large(tmp_path):
    big = tmp_path / "big.txt"
    big.write_text("x" * 200_000)
    out = expand_mentions(f"see @{big}", cwd=tmp_path, max_bytes=1000)
    assert "truncated" in out


def test_slash_command_loads_file(tmp_path):
    cmds = tmp_path / "cmds"
    cmds.mkdir()
    (cmds / "review.md").write_text("Please review the code.")
    assert expand_slash_command("/review", commands_dir=cmds) == "Please review the code."


def test_slash_command_with_args(tmp_path):
    cmds = tmp_path / "cmds"
    cmds.mkdir()
    (cmds / "fix.md").write_text("Fix the bug.")
    out = expand_slash_command("/fix in src/main.py", commands_dir=cmds)
    assert "Fix the bug." in out
    assert "in src/main.py" in out


def test_unknown_slash_command_unchanged(tmp_path):
    cmds = tmp_path / "cmds"
    cmds.mkdir()
    assert expand_slash_command("/nope", commands_dir=cmds) == "/nope"


def test_list_slash_commands(tmp_path):
    cmds = tmp_path / "cmds"
    cmds.mkdir()
    (cmds / "a.md").write_text("x")
    (cmds / "b.md").write_text("y")
    assert list_slash_commands(cmds) == ["a", "b"]


def test_preprocess_chains(tmp_path):
    cmds = tmp_path / "cmds"; cmds.mkdir()
    (cmds / "use.md").write_text("Use @data.txt to compute.")
    (tmp_path / "data.txt").write_text("[1, 2, 3]")
    out = preprocess("/use", commands_dir=cmds, cwd=tmp_path)
    assert "[1, 2, 3]" in out
