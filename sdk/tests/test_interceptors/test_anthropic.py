"""Tests for Anthropic interceptor using mocks."""

import sys
import types

import pytest


def _make_mock_anthropic():
    anthropic = types.ModuleType("anthropic")
    anthropic.resources = types.ModuleType("anthropic.resources")
    anthropic.resources.messages = types.ModuleType("anthropic.resources.messages")

    class MockUsage:
        input_tokens = 15
        output_tokens = 25

    class MockTextBlock:
        text = "Hello from Claude"

    class MockResponse:
        usage = MockUsage()
        content = [MockTextBlock()]

    class Messages:
        def create(self, *args, **kwargs):
            return MockResponse()

    class AsyncMessages:
        async def create(self, *args, **kwargs):
            return MockResponse()

    anthropic.resources.messages.Messages = Messages
    anthropic.resources.messages.AsyncMessages = AsyncMessages

    sys.modules["anthropic"] = anthropic
    sys.modules["anthropic.resources"] = anthropic.resources
    sys.modules["anthropic.resources.messages"] = anthropic.resources.messages
    return anthropic


def _cleanup():
    for key in list(sys.modules):
        if key.startswith("anthropic"):
            del sys.modules[key]


def test_patch_captures_events():
    mock = _make_mock_anthropic()
    try:
        from agentpulse.interceptors import anthropic as ant_int

        ant_int._patched = False
        ant_int._original_create = None
        ant_int._original_async_create = None

        captured = []
        ant_int.patch(enqueue_fn=captured.append)

        msgs = mock.resources.messages.Messages()
        result = msgs.create(model="claude-sonnet-4", messages=[{"role": "user", "content": "hi"}])

        assert len(captured) == 1
        event = captured[0]
        assert event["kind"] == "llm_call"
        assert event["data"]["provider"] == "anthropic"
        assert event["data"]["model"] == "claude-sonnet-4"
        assert event["data"]["input_tokens"] == 15
        assert event["data"]["output_tokens"] == 25
        assert event["data"]["status"] == "success"

        ant_int.unpatch()
    finally:
        _cleanup()


def test_patch_captures_errors():
    mock = _make_mock_anthropic()
    try:
        from agentpulse.interceptors import anthropic as ant_int

        ant_int._patched = False
        ant_int._original_create = None

        def failing(self, *a, **kw):
            raise ConnectionError("timeout")

        mock.resources.messages.Messages.create = failing

        captured = []
        ant_int.patch(enqueue_fn=captured.append)

        msgs = mock.resources.messages.Messages()
        with pytest.raises(ConnectionError):
            msgs.create(model="claude-sonnet-4", messages=[])

        assert captured[0]["data"]["status"] == "error"
        ant_int.unpatch()
    finally:
        _cleanup()
