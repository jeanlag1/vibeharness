import time

import pytest

from vibeharness.tools.bash import BashManager


@pytest.fixture
def mgr():
    m = BashManager()
    yield m
    m.shutdown()


def test_simple_command(mgr):
    res = mgr.run("echo hello")
    assert res["exit_code"] == 0
    assert "hello" in res["stdout"]
    assert res["timed_out"] is False


def test_exit_code_propagates(mgr):
    res = mgr.run("false")
    assert res["exit_code"] == 1


def test_session_persists_env(mgr):
    mgr.run("export FOO=bar", session_id="s1")
    res = mgr.run("echo $FOO", session_id="s1")
    assert "bar" in res["stdout"]


def test_session_persists_cwd(mgr, tmp_path):
    mgr.run(f"cd {tmp_path}", session_id="s2")
    res = mgr.run("pwd", session_id="s2")
    assert str(tmp_path) in res["stdout"]


def test_separate_sessions_isolated(mgr):
    mgr.run("export X=one", session_id="a")
    mgr.run("export X=two", session_id="b")
    a = mgr.run("echo $X", session_id="a")
    b = mgr.run("echo $X", session_id="b")
    assert "one" in a["stdout"]
    assert "two" in b["stdout"]


def test_timeout(mgr):
    res = mgr.run("sleep 5", timeout=1)
    assert res["timed_out"] is True


def test_background_process(mgr, tmp_path):
    marker = tmp_path / "done.txt"
    bg = mgr.start_background(f"sleep 0.3 && echo hi && touch {marker}")
    assert "bg_id" in bg
    # poll until done
    for _ in range(30):
        st = mgr.read_background(bg["bg_id"])
        if not st["running"]:
            break
        time.sleep(0.1)
    st = mgr.read_background(bg["bg_id"])
    assert st["running"] is False
    assert st["exit_code"] == 0
    assert "hi" in st["output"]
    assert marker.exists()


def test_background_stop(mgr):
    bg = mgr.start_background("sleep 30")
    res = mgr.stop_background(bg["bg_id"])
    assert res["stopped"] is True
    st = mgr.read_background(bg["bg_id"])
    assert st["running"] is False
