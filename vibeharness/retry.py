"""Rate-limit-aware retry wrapper for LLM provider calls.

Wraps any callable with exponential backoff + jitter on transient errors:
- HTTP 429 (rate limit)
- HTTP 529 / 'overloaded' (Anthropic overload)
- HTTP 5xx (server errors)
- network errors (APIConnectionError, Timeout)

Honors `Retry-After` headers when present. Surfaces a friendly status to a
UI hook so the user sees "rate limited, retrying in 4s…" instead of a hang.
"""
from __future__ import annotations

import os
import random
import time
from typing import Any, Callable, Optional

# Tunables (env-overridable)
MAX_RETRIES = int(os.environ.get("VIBE_MAX_RETRIES", "6"))
BASE_DELAY = float(os.environ.get("VIBE_RETRY_BASE_DELAY", "1.0"))
MAX_DELAY = float(os.environ.get("VIBE_RETRY_MAX_DELAY", "60.0"))


# We classify errors by inspection rather than importing provider exception
# classes (so this module stays optional-import-friendly).
_RETRYABLE_NAMES = {
    "RateLimitError",
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "ServiceUnavailableError",
    "OverloadedError",
    "Timeout",
    "ConnectionError",
}


def _status_code(exc: BaseException) -> Optional[int]:
    for attr in ("status_code", "http_status", "code"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    resp = getattr(exc, "response", None)
    if resp is not None:
        v = getattr(resp, "status_code", None)
        if isinstance(v, int):
            return v
    return None


def _retry_after(exc: BaseException) -> Optional[float]:
    headers = None
    resp = getattr(exc, "response", None)
    if resp is not None:
        headers = getattr(resp, "headers", None)
    headers = headers or getattr(exc, "headers", None)
    if not headers:
        return None
    try:
        v = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        return None
    if not v:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_retryable(exc: BaseException) -> bool:
    if exc.__class__.__name__ in _RETRYABLE_NAMES:
        return True
    code = _status_code(exc)
    if code in {408, 409, 425, 429, 500, 502, 503, 504, 529}:
        return True
    msg = str(exc).lower()
    if "rate limit" in msg or "overloaded" in msg or "try again" in msg:
        return True
    return False


def call_with_retry(
    fn: Callable[..., Any],
    *args,
    on_retry: Optional[Callable[[int, float, BaseException], None]] = None,
    max_retries: int = MAX_RETRIES,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs,
) -> Any:
    """Invoke fn(*args, **kwargs) with rate-limit-aware retries."""
    attempt = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - we re-raise non-retryable
            if not is_retryable(exc) or attempt >= max_retries:
                raise
            ra = _retry_after(exc)
            if ra is not None:
                delay = min(MAX_DELAY, ra)
            else:
                # Exponential backoff with full jitter.
                delay = min(MAX_DELAY, BASE_DELAY * (2 ** attempt))
                delay = random.uniform(0, delay)
            attempt += 1
            if on_retry:
                try:
                    on_retry(attempt, delay, exc)
                except Exception:
                    pass
            sleep(delay)
