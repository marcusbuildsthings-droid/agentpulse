"""AgentPulse SDK client — fire-and-forget event reporting."""

from __future__ import annotations

import atexit
import json
import os
import platform
import queue
import threading
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_DEFAULT_ENDPOINT = "https://api.agentpulse.dev"
_FLUSH_INTERVAL = 10.0  # seconds
_BATCH_SIZE = 50
_QUEUE_MAX = 5000


@dataclass
class Event:
    kind: str  # session, cron, cost, heartbeat, metric, alert
    ts: float = field(default_factory=time.time)
    data: dict = field(default_factory=dict)
    agent: str = ""
    session: str = ""


class AgentPulse:
    """Non-blocking event reporter with background flush."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        agent_name: Optional[str] = None,
        flush_interval: float = _FLUSH_INTERVAL,
        enabled: bool = True,
        debug: bool = False,
    ):
        self.api_key = api_key or os.environ.get("AGENTPULSE_API_KEY", "")
        self.endpoint = (endpoint or os.environ.get("AGENTPULSE_ENDPOINT", _DEFAULT_ENDPOINT)).rstrip("/")
        self.agent_name = agent_name or os.environ.get("AGENTPULSE_AGENT", platform.node())
        self.enabled = enabled and bool(self.api_key)
        self.debug = debug

        self._queue: queue.Queue[Event] = queue.Queue(maxsize=_QUEUE_MAX)
        self._active_sessions: dict[str, float] = {}  # session_key -> start_ts
        self._lock = threading.Lock()

        if self.enabled:
            self._worker = threading.Thread(target=self._flush_loop, args=(flush_interval,), daemon=True)
            self._worker.start()
            atexit.register(self.flush)

    # ── Public API ───────────────────────────────────────────────

    def session_start(self, key: str, metadata: Optional[dict] = None) -> None:
        """Mark a session as started."""
        with self._lock:
            self._active_sessions[key] = time.time()
        self._enqueue("session", data={"action": "start", **(metadata or {})}, session=key)

    def session_end(self, key: str, metadata: Optional[dict] = None) -> None:
        """Mark a session as ended."""
        start = self._active_sessions.pop(key, None)
        duration_ms = int((time.time() - start) * 1000) if start else None
        self._enqueue("session", data={"action": "end", "duration_ms": duration_ms, **(metadata or {})}, session=key)

    def session_event(self, key: str, event_type: str, data: Optional[dict] = None) -> None:
        """Log an arbitrary session event."""
        self._enqueue("session", data={"action": event_type, **(data or {})}, session=key)

    def cron_report(
        self,
        job_name: str,
        status: str = "ok",
        duration_ms: Optional[int] = None,
        summary: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Report a cron job run."""
        self._enqueue("cron", data={
            "job": job_name,
            "status": status,
            "duration_ms": duration_ms,
            "summary": summary,
            **(metadata or {}),
        })

    def cost_event(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: Optional[float] = None,
        session: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Report an API cost event."""
        self._enqueue("cost", data={
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost,
            **(metadata or {}),
        }, session=session or "")

    def heartbeat(self, metadata: Optional[dict] = None) -> None:
        """Send a heartbeat ping."""
        self._enqueue("heartbeat", data={
            "active_sessions": len(self._active_sessions),
            **(metadata or {}),
        })

    def metric(self, name: str, value: float, tags: Optional[dict] = None) -> None:
        """Report a custom metric."""
        self._enqueue("metric", data={"name": name, "value": value, "tags": tags or {}})

    def alert(self, title: str, severity: str = "warning", details: Optional[str] = None) -> None:
        """Send an alert."""
        self._enqueue("alert", data={"title": title, "severity": severity, "details": details})

    def memory_report(
        self,
        file: str,
        size_bytes: int,
        lines: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """Report memory file status."""
        self._enqueue("memory", data={
            "file": file,
            "size_bytes": size_bytes,
            "lines": lines,
            **(metadata or {}),
        })

    # ── Flush / Transport ────────────────────────────────────────

    def flush(self) -> int:
        """Flush pending events. Returns count sent."""
        batch: list[Event] = []
        while not self._queue.empty() and len(batch) < _BATCH_SIZE * 10:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break

        if not batch:
            return 0

        payload = {
            "agent": self.agent_name,
            "events": [asdict(e) for e in batch],
        }
        try:
            self._post("/v1/ingest", payload)
        except Exception as exc:
            if self.debug:
                print(f"[agentpulse] flush error: {exc}")
            # Re-queue on failure (best effort, may lose some)
            for e in batch[:_QUEUE_MAX // 2]:
                try:
                    self._queue.put_nowait(e)
                except queue.Full:
                    break
            return 0

        return len(batch)

    def _post(self, path: str, payload: dict) -> dict:
        """HTTP POST with urllib (no dependencies)."""
        url = self.endpoint + path
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": f"agentpulse-python/{__import__('agentpulse').__version__}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    def _enqueue(self, kind: str, data: dict, session: str = "") -> None:
        if not self.enabled:
            return
        event = Event(kind=kind, data=data, agent=self.agent_name, session=session)
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            if self.debug:
                print("[agentpulse] queue full, dropping event")

    def _flush_loop(self, interval: float) -> None:
        while True:
            time.sleep(interval)
            self.flush()


# ── Module-level singleton ───────────────────────────────────────

pulse = AgentPulse()


def init(
    api_key: Optional[str] = None,
    endpoint: Optional[str] = None,
    agent_name: Optional[str] = None,
    **kwargs: Any,
) -> AgentPulse:
    """Initialize the global pulse instance."""
    global pulse
    pulse = AgentPulse(api_key=api_key, endpoint=endpoint, agent_name=agent_name, **kwargs)
    return pulse
