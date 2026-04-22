"""User-facing config: API keys, model, defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib  # py311+
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore

CONFIG_PATH = Path.home() / ".vibe" / "config.toml"


@dataclass
class Config:
    provider: str = "anthropic"
    model: str | None = None
    permission_mode: str = "ask"  # auto | ask | deny
    max_iters: int = 50
    max_context_tokens: int = 120_000


def load() -> Config:
    cfg = Config()
    if CONFIG_PATH.exists() and tomllib:
        try:
            data = tomllib.loads(CONFIG_PATH.read_text())
        except Exception:
            data = {}
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
    # Env overrides
    if env := os.environ.get("VIBE_PROVIDER"):
        cfg.provider = env
    if env := os.environ.get("VIBE_MODEL"):
        cfg.model = env
    if env := os.environ.get("VIBE_PERMISSION_MODE"):
        cfg.permission_mode = env
    return cfg
