from vibeharness.tools.bash import _smart_truncate, _strip_ansi


def test_strip_ansi():
    s = "\x1b[31mred\x1b[0m text"
    assert _strip_ansi(s) == "red text"


def test_collapse_repeated_lines():
    s = "x\n" * 50
    out = _smart_truncate(s, 10_000)
    assert "repeated 50x" in out
    assert out.count("\n") < 5


def test_truncate_long():
    s = "a" * 5000
    out = _smart_truncate(s, 1000)
    assert "truncated" in out
    assert len(out) < 1500
