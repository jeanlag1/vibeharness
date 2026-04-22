from vibeharness.pricing import estimate_cost, format_cost


def test_estimate_known_model():
    cost = estimate_cost("claude-sonnet-4-5", 1_000_000, 100_000)
    # 1M in * $3 + 100k out * $15 = 3 + 1.5 = 4.50
    assert cost == 4.5


def test_cache_pricing_applied():
    cost = estimate_cost("claude-sonnet-4-5", 0, 0, cache_read_tokens=1_000_000)
    assert cost == 0.30


def test_unknown_model_returns_none():
    assert estimate_cost("totally-fake-model-xyz", 100, 100) is None


def test_format_cost():
    assert format_cost(0.1234) == "$0.1234"
    assert "¢" in format_cost(0.005)
    assert format_cost(None) == "$?"
