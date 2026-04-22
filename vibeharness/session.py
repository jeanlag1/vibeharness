"""Session persistence: save and resume conversations as JSON."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

DEFAULT_SESSION_DIR = Path.home() / ".vibe" / "sessions"


@dataclass
class SessionMeta:
    id: str
    created_at: float
    provider: str
    model: str
    cwd: str


def _ensure_dir() -> Path:
    DEFAULT_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_SESSION_DIR


def session_path(session_id: str) -> Path:
    return _ensure_dir() / f"{session_id}.json"


def save_session(session_id: str, meta: SessionMeta, messages: list[dict],
                 in_tokens: int, out_tokens: int) -> Path:
    p = session_path(session_id)
    payload = {
        "meta": asdict(meta),
        "messages": messages,
        "tokens": {"input": in_tokens, "output": out_tokens},
        "saved_at": time.time(),
    }
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return p


def load_session(session_id: str) -> Optional[dict]:
    p = session_path(session_id)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def list_sessions() -> list[dict]:
    if not DEFAULT_SESSION_DIR.exists():
        return []
    out = []
    for p in sorted(DEFAULT_SESSION_DIR.glob("*.json"), key=lambda x: -x.stat().st_mtime):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            meta = data.get("meta", {})
            out.append({
                "id": meta.get("id", p.stem),
                "created_at": meta.get("created_at"),
                "model": meta.get("model"),
                "cwd": meta.get("cwd"),
                "messages": len(data.get("messages", [])),
            })
        except Exception:
            continue
    return out
