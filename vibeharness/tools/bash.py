"""Bash tool with persistent shell sessions.

Backed by `pexpect` so we get a real PTY, env vars survive between calls,
and `cd` works as expected. Supports:

- foreground commands with timeout
- background processes (returns a handle; output captured to a temp file)
- session reuse via `session_id`
"""
from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import pexpect

DEFAULT_TIMEOUT = 120  # seconds
MAX_OUTPUT_BYTES = 100_000

# A unique sentinel printed after every command so we know when output ends.
_SENTINEL = "__VIBE_DONE__"

# Strip ANSI color escape sequences from captured output.
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _smart_truncate(s: str, limit: int = MAX_OUTPUT_BYTES) -> str:
    """Trim long output by keeping head + tail and collapsing run-length-encodable lines."""
    s = _strip_ansi(s)
    # Collapse runs of identical lines (e.g. download progress) to '...(xN)'.
    out_lines: list[str] = []
    last: str | None = None
    rep = 0
    for line in s.splitlines():
        if line == last:
            rep += 1
            continue
        if rep:
            out_lines.append(f"  ...(repeated {rep+1}x)")
            rep = 0
        out_lines.append(line)
        last = line
    if rep:
        out_lines.append(f"  ...(repeated {rep+1}x)")
    s = "\n".join(out_lines)
    if len(s) <= limit:
        return s
    head = s[: limit // 2]
    tail = s[-limit // 2 :]
    return head + f"\n...[truncated {len(s) - limit} bytes]...\n" + tail


class ToolError(Exception):
    pass


@dataclass
class _Session:
    shell: pexpect.spawn
    cwd: str


@dataclass
class _BgProcess:
    pid: int
    cmd: str
    log_path: str
    proc: subprocess.Popen
    started_at: float = field(default_factory=time.time)


class BashManager:
    """Manages persistent shell sessions and background processes."""

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._bg: dict[str, _BgProcess] = {}

    # ---------- foreground ----------
    def _ensure(self, session_id: str) -> _Session:
        if session_id not in self._sessions:
            shell = pexpect.spawn(
                "/bin/bash",
                ["--noprofile", "--norc"],
                encoding="utf-8",
                echo=False,
                timeout=DEFAULT_TIMEOUT,
                dimensions=(40, 120),
            )
            shell.sendline("export PS1=''")
            shell.sendline("stty -echo 2>/dev/null || true")
            self._sessions[session_id] = _Session(shell=shell, cwd=os.getcwd())
            # Drain any startup noise.
            try:
                shell.expect(pexpect.TIMEOUT, timeout=0.2)
            except Exception:
                pass
        return self._sessions[session_id]

    def run(
        self,
        command: str,
        session_id: str = "default",
        timeout: int = DEFAULT_TIMEOUT,
    ) -> dict:
        sess = self._ensure(session_id)
        # Wrap command so we capture exit code + a sentinel marking completion.
        wrapped = f"{command}\necho {_SENTINEL}:$?"
        sess.shell.sendline(wrapped)
        try:
            sess.shell.expect(rf"{_SENTINEL}:(\d+)", timeout=timeout)
            exit_code = int(sess.shell.match.group(1))
            output = sess.shell.before or ""
        except pexpect.TIMEOUT:
            sess.shell.sendcontrol("c")
            try:
                sess.shell.expect(rf"{_SENTINEL}:(\d+)", timeout=2)
            except Exception:
                pass
            return {
                "stdout": (sess.shell.before or "")[-MAX_OUTPUT_BYTES:],
                "exit_code": -1,
                "timed_out": True,
                "session_id": session_id,
            }
        except pexpect.EOF:
            raise ToolError("shell session died unexpectedly")

        if len(output) > MAX_OUTPUT_BYTES or "\x1b" in output:
            output = _smart_truncate(output, MAX_OUTPUT_BYTES)
        return {
            "stdout": output,
            "exit_code": exit_code,
            "timed_out": False,
            "session_id": session_id,
        }

    # ---------- background ----------
    def start_background(self, command: str) -> dict:
        log_path = tempfile.mktemp(prefix="vibe_bg_", suffix=".log")
        log = open(log_path, "wb")
        proc = subprocess.Popen(
            ["/bin/bash", "-lc", command],
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        bg_id = uuid.uuid4().hex[:8]
        self._bg[bg_id] = _BgProcess(pid=proc.pid, cmd=command, log_path=log_path, proc=proc)
        return {"bg_id": bg_id, "pid": proc.pid, "log_path": log_path}

    def read_background(self, bg_id: str, tail: int = 4000) -> dict:
        if bg_id not in self._bg:
            raise ToolError(f"unknown bg_id: {bg_id}")
        bg = self._bg[bg_id]
        try:
            with open(bg.log_path, "rb") as f:
                data = f.read()
        except FileNotFoundError:
            data = b""
        text = _strip_ansi(data.decode("utf-8", errors="replace"))
        if len(text) > tail:
            text = "...[truncated]...\n" + text[-tail:]
        rc = bg.proc.poll()
        return {
            "bg_id": bg_id,
            "running": rc is None,
            "exit_code": rc,
            "output": text,
            "uptime_s": round(time.time() - bg.started_at, 1),
        }

    def stop_background(self, bg_id: str) -> dict:
        if bg_id not in self._bg:
            raise ToolError(f"unknown bg_id: {bg_id}")
        bg = self._bg[bg_id]
        if bg.proc.poll() is None:
            try:
                os.killpg(os.getpgid(bg.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                bg.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(bg.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        return {"bg_id": bg_id, "stopped": True, "exit_code": bg.proc.returncode}

    def shutdown(self) -> None:
        for bg_id in list(self._bg):
            try:
                self.stop_background(bg_id)
            except Exception:
                pass
        for sess in self._sessions.values():
            try:
                sess.shell.close(force=True)
            except Exception:
                pass
        self._sessions.clear()
        self._bg.clear()


# Module-level singleton; the agent loop owns it.
_manager: Optional[BashManager] = None


def get_manager() -> BashManager:
    global _manager
    if _manager is None:
        _manager = BashManager()
    return _manager


def run_bash(command: str, session_id: str = "default", timeout: int = DEFAULT_TIMEOUT) -> dict:
    return get_manager().run(command, session_id=session_id, timeout=timeout)


def run_bash_background(command: str) -> dict:
    return get_manager().start_background(command)


def read_bash_background(bg_id: str, tail: int = 4000) -> dict:
    return get_manager().read_background(bg_id, tail=tail)


def stop_bash_background(bg_id: str) -> dict:
    return get_manager().stop_background(bg_id)
