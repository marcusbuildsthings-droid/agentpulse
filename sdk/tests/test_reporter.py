"""Tests for the background reporter."""

import gzip
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import List

from agentpulse.reporter import Reporter


class _MockHandler(BaseHTTPRequestHandler):
    received: List[dict] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        encoding = self.headers.get("Content-Encoding", "")
        if encoding == "gzip":
            body = gzip.decompress(body)
        payload = json.loads(body)
        _MockHandler.received.append(payload)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):
        pass  # Suppress logs


def _start_mock_server():
    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def test_enqueue_and_flush():
    _MockHandler.received.clear()
    server = _start_mock_server()
    port = server.server_address[1]

    reporter = Reporter(
        endpoint=f"http://127.0.0.1:{port}",
        api_key="test-key",
        agent_name="test",
        flush_interval=60.0,  # We'll flush manually
    )
    reporter.start()

    reporter.enqueue({"kind": "test", "ts": time.time(), "data": {"x": 1}})
    reporter.enqueue({"kind": "test", "ts": time.time(), "data": {"x": 2}})
    reporter._flush()

    time.sleep(0.5)
    assert len(_MockHandler.received) == 1
    payload = _MockHandler.received[0]
    assert payload["agent"] == "test"
    assert len(payload["events"]) == 2

    reporter.shutdown()
    server.shutdown()


def test_empty_flush():
    """Flushing with no events should be a no-op."""
    reporter = Reporter(endpoint="http://localhost:9999", api_key="x", flush_interval=60.0)
    reporter.start()
    reporter._flush()  # Should not raise
    reporter.shutdown()


def test_max_queue_size():
    reporter = Reporter(endpoint="http://localhost:9999", api_key="x", max_queue_size=5, flush_interval=60.0)
    for i in range(10):
        reporter.enqueue({"i": i})
    assert len(reporter._queue) == 5  # Oldest dropped


def test_gzip_compression():
    _MockHandler.received.clear()
    server = _start_mock_server()
    port = server.server_address[1]

    reporter = Reporter(endpoint=f"http://127.0.0.1:{port}", api_key="test", flush_interval=60.0)
    reporter.start()
    reporter.enqueue({"kind": "test", "data": {}})
    reporter._flush()
    time.sleep(0.5)

    assert len(_MockHandler.received) == 1
    reporter.shutdown()
    server.shutdown()
