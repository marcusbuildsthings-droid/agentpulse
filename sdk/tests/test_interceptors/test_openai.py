"""Tests for OpenAI interceptor using mocks."""

import sys
import types
from unittest.mock import MagicMock

import pytest


def _make_mock_openai():
    """Create a mock openai module structure."""
    # Build module hierarchy
    openai = types.ModuleType("openai")
    openai.resources = types.ModuleType("openai.resources")
    openai.resources.chat = types.ModuleType("openai.resources.chat")
    openai.resources.chat.completions = types.ModuleType("openai.resources.chat.completions")

    class MockUsage:
        prompt_tokens = 10
        completion_tokens = 20

    class MockMessage:
        content = "Hello world"

    class MockChoice:
        message = MockMessage()

    class MockResponse:
        usage = MockUsage()
        choices = [MockChoice()]

    class Completions:
        def create(self, *args, **kwargs):
            return MockResponse()

    class AsyncCompletions:
        async def create(self, *args, **kwargs):
            return MockResponse()

    openai.resources.chat.completions.Completions = Completions
    openai.resources.chat.completions.AsyncCompletions = AsyncCompletions

    # Register in sys.modules
    sys.modules["openai"] = openai
    sys.modules["openai.resources"] = openai.resources
    sys.modules["openai.resources.chat"] = openai.resources.chat
    sys.modules["openai.resources.chat.completions"] = openai.resources.chat.completions
    return openai


def _cleanup_openai():
    for key in list(sys.modules):
        if key.startswith("openai"):
            del sys.modules[key]


def test_patch_captures_events():
    mock_openai = _make_mock_openai()
    try:
        from agentpulse.interceptors import openai as oai_int

        # Reset state
        oai_int._patched = False
        oai_int._original_create = None
        oai_int._original_async_create = None

        captured = []
        oai_int.patch(enqueue_fn=captured.append, capture_messages=False)

        comp = mock_openai.resources.chat.completions.Completions()
        result = comp.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])

        assert len(captured) == 1
        event = captured[0]
        assert event["kind"] == "llm_call"
        assert event["data"]["provider"] == "openai"
        assert event["data"]["model"] == "gpt-4o"
        assert event["data"]["input_tokens"] == 10
        assert event["data"]["output_tokens"] == 20
        assert event["data"]["status"] == "success"
        assert "cost_usd" in event["data"]
        assert event["data"]["latency_ms"] >= 0

        oai_int.unpatch()
    finally:
        _cleanup_openai()


def test_patch_captures_errors():
    mock_openai = _make_mock_openai()
    try:
        from agentpulse.interceptors import openai as oai_int

        oai_int._patched = False
        oai_int._original_create = None

        # Make create raise
        original = mock_openai.resources.chat.completions.Completions.create

        def failing_create(self, *a, **kw):
            raise ValueError("API error")

        mock_openai.resources.chat.completions.Completions.create = failing_create

        captured = []
        oai_int.patch(enqueue_fn=captured.append)

        comp = mock_openai.resources.chat.completions.Completions()
        with pytest.raises(ValueError, match="API error"):
            comp.create(model="gpt-4o", messages=[])

        assert len(captured) == 1
        assert captured[0]["data"]["status"] == "error"
        assert "API error" in captured[0]["data"]["error"]

        oai_int.unpatch()
    finally:
        _cleanup_openai()


def test_unpatch_restores():
    mock_openai = _make_mock_openai()
    try:
        from agentpulse.interceptors import openai as oai_int

        oai_int._patched = False
        oai_int._original_create = None

        original = mock_openai.resources.chat.completions.Completions.create
        oai_int.patch(enqueue_fn=lambda e: None)
        assert mock_openai.resources.chat.completions.Completions.create is not original

        oai_int.unpatch()
        assert mock_openai.resources.chat.completions.Completions.create is original
    finally:
        _cleanup_openai()
