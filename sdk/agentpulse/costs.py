"""LLM cost lookup table with fuzzy model matching."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

# Cost per 1K tokens: (input, output)
COST_TABLE: Dict[str, Tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "o1": (0.015, 0.06),
    "o1-mini": (0.003, 0.012),
    "o1-pro": (0.15, 0.60),
    "o3": (0.01, 0.04),
    "o3-mini": (0.0011, 0.0044),
    "o4-mini": (0.0011, 0.0044),
    # Anthropic
    "claude-opus-4": (0.015, 0.075),
    "claude-opus-4-0": (0.015, 0.075),
    "claude-sonnet-4": (0.003, 0.015),
    "claude-sonnet-4-0": (0.003, 0.015),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-5-haiku": (0.0008, 0.004),
    "claude-3-opus": (0.015, 0.075),
    "claude-3-sonnet": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
    # Google
    "gemini-2.0-flash": (0.0001, 0.0004),
    "gemini-1.5-pro": (0.00125, 0.005),
    "gemini-1.5-flash": (0.000075, 0.0003),
    # Meta (via API providers)
    "llama-3.1-70b": (0.00035, 0.0004),
    "llama-3.1-8b": (0.00005, 0.00008),
    # Mistral
    "mistral-large": (0.002, 0.006),
    "mistral-small": (0.0002, 0.0006),
    # Cohere
    "command-r-plus": (0.003, 0.015),
    "command-r": (0.0005, 0.0015),
}

# User overrides merged at runtime
_overrides: Dict[str, Tuple[float, float]] = {}


def set_cost_overrides(overrides: Dict[str, Tuple[float, float]]) -> None:
    """Merge user-provided cost overrides."""
    _overrides.update(overrides)


def _normalize(model: str) -> str:
    """Strip date suffixes and common prefixes for fuzzy matching."""
    m = model.lower().strip()
    # Remove common provider prefixes
    for prefix in ("openai/", "anthropic/", "google/", "meta/", "accounts/fireworks/models/"):
        if m.startswith(prefix):
            m = m[len(prefix):]
    # Remove date suffixes like -2024-08-06, -20241022
    parts = m.rsplit("-", 1)
    if len(parts) == 2 and len(parts[1]) >= 8 and parts[1].replace("-", "").isdigit():
        m = parts[0]
    return m


def _lookup(model: str) -> Optional[Tuple[float, float]]:
    norm = _normalize(model)
    # Exact match first
    if norm in _overrides:
        return _overrides[norm]
    if norm in COST_TABLE:
        return COST_TABLE[norm]
    # Prefix match (e.g. "gpt-4o-2024-08-06" -> "gpt-4o")
    for key in sorted(COST_TABLE, key=len, reverse=True):
        if norm.startswith(key):
            return _overrides.get(key, COST_TABLE[key])
    return None


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    """Calculate cost in USD. Returns None if model not found."""
    costs = _lookup(model)
    if costs is None:
        return None
    input_cost, output_cost = costs
    return (input_tokens / 1000) * input_cost + (output_tokens / 1000) * output_cost
