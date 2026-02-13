"""End-to-end integration test with mock server."""

import gzip
import json
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


class _IngestHandler(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if self.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        _IngestHandler.received.append(json.loads(body))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *a):
        pass


def _setup_mock_openai():
    """Inject a mock openai module."""
    openai = types.ModuleType("openai")
    openai.resources = types.ModuleType("openai.resources")
    openai.resources.chat = types.ModuleType("openai.resources.chat")
    openai.resources.chat.completions = types.ModuleType("openai.resources.chat.completions")

    class MockUsage:
        prompt_tokens = 50
        completion_tokens = 100

    class MockMessage:
        content = "Test response"

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

    sys.modules["openai"] = openai
    sys.modules["openai.resources"] = openai.resources
    sys.modules["openai.resources.chat"] = openai.resources.chat
    sys.modules["openai.resources.chat.completions"] = openai.resources.chat.completions
    return openai


def test_full_pipeline():
    """init() -> openai call -> events flushed to mock server."""
    _IngestHandler.received.clear()

    server = HTTPServer(("127.0.0.1", 0), _IngestHandler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    mock_openai = _setup_mock_openai()

    try:
        # Reset client singleton
        import agentpulse.client as client_mod
        client_mod._client = None

        # Reset interceptor state
        from agentpulse.interceptors import openai as oai_int
        oai_int._patched = False
        oai_int._original_create = None
        oai_int._original_async_create = None

        from agentpulse.interceptors import _patched_libs
        _patched_libs.clear()

        import agentpulse
        client = agentpulse.init(
            api_key="test-key",
            endpoint=f"http://127.0.0.1:{port}",
            agent_name="integration-test",
        )

        # Make an "OpenAI" call
        comp = mock_openai.resources.chat.completions.Completions()
        result = comp.create(model="gpt-4o", messages=[{"role": "user", "content": "test"}])

        # Flush
        client.flush()
        time.sleep(1.0)

        # Should have received events (init + llm_call)
        assert len(_IngestHandler.received) >= 1
        all_events = []
        for payload in _IngestHandler.received:
            assert payload["agent"] == "integration-test"
            all_events.extend(payload["events"])

        kinds = [e["kind"] for e in all_events]
        assert "sdk_init" in kinds
        assert "llm_call" in kinds

        llm_event = next(e for e in all_events if e["kind"] == "llm_call")
        assert llm_event["data"]["model"] == "gpt-4o"
        assert llm_event["data"]["input_tokens"] == 50
        assert llm_event["data"]["output_tokens"] == 100

        agentpulse.shutdown()
    finally:
        for key in list(sys.modules):
            if key.startswith("openai"):
                del sys.modules[key]
        server.shutdown()
