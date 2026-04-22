"""Approximate per-token pricing in USD.

Numbers in USD per 1M tokens. Update as needed; vendors change prices.
"""
from __future__ import annotations

PRICING: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-4": {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    "claude-haiku-4": {"input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_write": 1.00},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    # OpenAI
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-5-mini": {"input": 0.25, "output": 2.00},
}


def _match(model: str) -> dict[str, float] | None:
    if model in PRICING:
        return PRICING[model]
    # Fuzzy: longest prefix match
    best = None
    for k in PRICING:
        if model.startswith(k) or k.startswith(model.split("-2")[0]):
            if best is None or len(k) > len(best):
                best = k
    return PRICING.get(best) if best else None


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    """Return estimated USD cost, or None if model not in pricing table."""
    p = _match(model)
    if not p:
        return None
    cost = (input_tokens / 1_000_000) * p.get("input", 0)
    cost += (output_tokens / 1_000_000) * p.get("output", 0)
    cost += (cache_read_tokens / 1_000_000) * p.get("cache_read", p.get("input", 0))
    cost += (cache_write_tokens / 1_000_000) * p.get("cache_write", p.get("input", 0))
    return cost


def format_cost(usd: float | None) -> str:
    if usd is None:
        return "$?"
    if usd < 0.01:
        return f"${usd*100:.2f}¢"
    return f"${usd:.4f}"
