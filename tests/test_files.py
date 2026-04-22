import pytest
from pathlib import Path

from vibeharness.tools.files import (
    ToolError,
    edit_file,
    glob_files,
    grep,
    list_dir,
    read_file,
    write_file,
)


def test_write_and_read(tmp_path):
    p = tmp_path / "hello.txt"
    res = write_file(str(p), "hello\nworld\n")
    assert res["created"] is True
    assert res["bytes_written"] == 12
    out = read_file(str(p))
    assert out["content"] == "hello\nworld\n"
    assert out["total_lines"] == 2
    assert out["truncated"] is False


def test_read_offset_limit(tmp_path):
    p = tmp_path / "f.txt"
    write_file(str(p), "".join(f"L{i}\n" for i in range(10)))
    out = read_file(str(p), offset=3, limit=2)
    assert out["content"] == "L3\nL4\n"
    assert out["total_lines"] == 10


def test_read_missing(tmp_path):
    with pytest.raises(ToolError):
        read_file(str(tmp_path / "nope"))


def test_edit_unique(tmp_path):
    p = tmp_path / "f.py"
    write_file(str(p), "x = 1\ny = 2\n")
    res = edit_file(str(p), "x = 1", "x = 42")
    assert res["replacements"] == 1
    assert read_file(str(p))["content"] == "x = 42\ny = 2\n"


def test_edit_ambiguous_fails(tmp_path):
    p = tmp_path / "f.py"
    write_file(str(p), "a\na\n")
    with pytest.raises(ToolError, match="found 2"):
        edit_file(str(p), "a", "b")


def test_edit_all(tmp_path):
    p = tmp_path / "f.py"
    write_file(str(p), "a\na\n")
    res = edit_file(str(p), "a", "b", count=-1)
    assert res["replacements"] == 2
    assert read_file(str(p))["content"] == "b\nb\n"


def test_edit_missing_string(tmp_path):
    p = tmp_path / "f.py"
    write_file(str(p), "abc\n")
    with pytest.raises(ToolError, match="not found"):
        edit_file(str(p), "xyz", "q")


def test_grep_basic(tmp_path):
    write_file(str(tmp_path / "a.py"), "def foo():\n    pass\n")
    write_file(str(tmp_path / "b.py"), "def bar():\n    pass\n")
    res = grep("def ", str(tmp_path))
    assert res["truncated"] is False
    assert len(res["matches"]) == 2
    assert {m["file"].split("/")[-1] for m in res["matches"]} == {"a.py", "b.py"}


def test_grep_glob(tmp_path):
    write_file(str(tmp_path / "a.py"), "needle\n")
    write_file(str(tmp_path / "b.txt"), "needle\n")
    res = grep("needle", str(tmp_path), glob="*.py")
    assert len(res["matches"]) == 1
    assert res["matches"][0]["file"].endswith("a.py")


def test_grep_invalid_regex(tmp_path):
    with pytest.raises(ToolError):
        grep("[unclosed", str(tmp_path))


def test_glob_files(tmp_path):
    write_file(str(tmp_path / "a/b/c.py"), "x")
    write_file(str(tmp_path / "a/d.py"), "x")
    res = glob_files("**/*.py", str(tmp_path))
    assert res["count"] == 2


def test_list_dir(tmp_path):
    write_file(str(tmp_path / "f.txt"), "x")
    (tmp_path / "sub").mkdir()
    res = list_dir(str(tmp_path))
    assert "f.txt" in res["entries"]
    assert "sub/" in res["entries"]
