"""Tests for auto-detection logic."""

import sys
from unittest.mock import patch

from agentpulse.interceptors import _patched_libs, patch_all, unpatch_all


def test_patch_all_no_libs():
    """When no LLM libs are installed, patch_all returns empty."""
    # Ensure none are in sys.modules
    for lib in ("openai", "anthropic", "litellm"):
        sys.modules.pop(lib, None)

    unpatch_all()
    _patched_libs.clear()

    result = patch_all(enqueue_fn=lambda e: None, enabled={"patch_openai": False, "patch_anthropic": False})
    assert result == []


def test_unpatch_all_is_safe():
    """unpatch_all should be safe to call even if nothing was patched."""
    unpatch_all()  # Should not raise
