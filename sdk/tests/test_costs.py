"""Tests for cost calculation."""

from agentpulse.costs import calculate_cost, set_cost_overrides


def test_known_model():
    cost = calculate_cost("gpt-4o", 1000, 1000)
    assert cost is not None
    assert abs(cost - 0.0125) < 0.001  # 0.0025 + 0.01


def test_unknown_model():
    cost = calculate_cost("totally-unknown-model-xyz", 1000, 1000)
    assert cost is None


def test_fuzzy_match_date_suffix():
    cost = calculate_cost("gpt-4o-2024-08-06", 1000, 500)
    assert cost is not None


def test_fuzzy_match_prefix():
    cost = calculate_cost("openai/gpt-4o", 1000, 1000)
    assert cost is not None


def test_zero_tokens():
    cost = calculate_cost("gpt-4o", 0, 0)
    assert cost == 0.0


def test_anthropic_model():
    cost = calculate_cost("claude-sonnet-4", 1000, 1000)
    assert cost is not None
    assert abs(cost - 0.018) < 0.001


def test_cost_override():
    set_cost_overrides({"custom-model": (0.001, 0.002)})
    cost = calculate_cost("custom-model", 1000, 1000)
    assert cost is not None
    assert abs(cost - 0.003) < 0.0001
