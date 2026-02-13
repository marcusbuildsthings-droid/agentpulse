"""Background batch reporter — daemon thread, gzip, retry, zero deps."""

from __future__ import annotations

import atexit
import gzip
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("agentpulse")


class Reporter:
    """Batched, compressed, non-blocking event sender."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        agent_name: str = "default",
        sdk_version: str = "0.1.0",
        flush_interval: float = 5.0,
        max_queue_size: int = 10_000,
        max_batch_size: int = 100,
        max_retries: int = 3,
        debug: bool = False,
    ) -> None:
        self._endpoint = endpoint.rstrip("/") + "/v1/ingest"
        self._api_key = api_key
        self._agent_name = agent_name
        self._sdk_version = sdk_version
        self._flush_interval = flush_interval
        self._max_batch_size = max_batch_size
        self._max_retries = max_retries
        self._debug = debug

        self._queue: Deque[Dict[str, Any]] = deque(maxlen=max_queue_size)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._started = False

    # -- lifecycle --

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="agentpulse-reporter")
        self._thread.start()
        atexit.register(self.shutdown)

    def shutdown(self, timeout: float = 5.0) -> None:
        if not self._started:
            return
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._flush()
        self._started = False

    # -- public --

    def enqueue(self, event: Dict[str, Any]) -> None:
        """Thread-safe fire-and-forget enqueue."""
        with self._lock:
            self._queue.append(event)

    # -- internals --

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self._flush_interval)
            self._flush()

    def _flush(self) -> None:
        with self._lock:
            if not self._queue:
                return
            batch = list(self._queue)
            self._queue.clear()

        # Send in chunks of max_batch_size
        for i in range(0, len(batch), self._max_batch_size):
            chunk = batch[i : i + self._max_batch_size]
            self._send(chunk)

    def _send(self, events: List[Dict[str, Any]]) -> None:
        payload = {
            "agent": self._agent_name,
            "sdk_version": self._sdk_version,
            "events": events,
        }
        body = gzip.compress(json.dumps(payload, default=str).encode("utf-8"))

        for attempt in range(self._max_retries):
            try:
                req = urllib.request.Request(
                    self._endpoint,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Content-Encoding": "gzip",
                        "Authorization": f"Bearer {self._api_key}",
                        "User-Agent": f"agentpulse-python/{self._sdk_version}",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status < 300:
                        if self._debug:
                            logger.debug("Flushed %d events", len(events))
                        return
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                if self._debug:
                    logger.debug("Send attempt %d failed: %s", attempt + 1, exc)
                if attempt < self._max_retries - 1:
                    time.sleep(min(2**attempt, 8))
            except Exception as exc:
                if self._debug:
                    logger.debug("Send failed (non-retryable): %s", exc)
                return  # drop on unexpected errors

        if self._debug:
            logger.warning("Dropped %d events after %d retries", len(events), self._max_retries)
