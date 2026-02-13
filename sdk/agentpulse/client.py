"""AgentPulse client — singleton orchestrator for init/shutdown/manual events."""

from __future__ import annotations

import logging
import os
import platform
import sys
import time
from typing import Any, Dict, Optional

from agentpulse.context import Span, get_current_span
from agentpulse.costs import set_cost_overrides
from agentpulse.interceptors import patch_all, unpatch_all
from agentpulse.reporter import Reporter

logger = logging.getLogger("agentpulse")

_VERSION = "0.1.0"

_client: Optional["AgentPulseClient"] = None


def _bool_env(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "").lower()
    if val in ("1", "true", "yes"):
        return True
    if val in ("0", "false", "no"):
        return False
    return default


class AgentPulseClient:
    """Core client — manages reporter, interceptors, and manual event API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        agent_name: Optional[str] = None,
        endpoint: Optional[str] = None,
        enabled: Optional[bool] = None,
        capture_messages: Optional[bool] = None,
        auto_patch: Optional[bool] = None,
        flush_interval: float = 5.0,
        max_queue_size: int = 10_000,
        max_batch_size: int = 100,
        debug: Optional[bool] = None,
        cost_table_override: Optional[Dict[str, Any]] = None,
        **patch_kwargs: Any,
    ) -> None:
        # Resolve config: kwargs > env > defaults
        self.api_key = api_key or os.environ.get("AGENTPULSE_API_KEY", "")
        self.agent_name = agent_name or os.environ.get("AGENTPULSE_AGENT", platform.node())
        self.endpoint = endpoint or os.environ.get("AGENTPULSE_ENDPOINT", "https://api.agentpulse.dev")
        self.enabled = enabled if enabled is not None else _bool_env("AGENTPULSE_ENABLED", True)
        self.capture_messages = capture_messages if capture_messages is not None else _bool_env("AGENTPULSE_CAPTURE_MESSAGES", False)
        self.auto_patch = auto_patch if auto_patch is not None else _bool_env("AGENTPULSE_AUTO_PATCH", True)
        self.debug = debug if debug is not None else _bool_env("AGENTPULSE_DEBUG", False)
        self._patch_kwargs = patch_kwargs

        if self.debug:
            logging.basicConfig(level=logging.DEBUG, format="[agentpulse] %(message)s", stream=sys.stderr)

        if not self.enabled:
            logger.debug("AgentPulse disabled")
            self._reporter = None
            return

        if not self.api_key:
            logger.warning("AGENTPULSE_API_KEY not set — events will be queued but not sent")

        # Cost overrides
        if cost_table_override:
            set_cost_overrides(cost_table_override)

        # Start reporter
        self._reporter = Reporter(
            endpoint=self.endpoint,
            api_key=self.api_key,
            agent_name=self.agent_name,
            sdk_version=_VERSION,
            flush_interval=flush_interval,
            max_queue_size=max_queue_size,
            max_batch_size=max_batch_size,
            debug=self.debug,
        )
        self._reporter.start()

        # Auto-patch
        if self.auto_patch:
            patched = patch_all(
                enqueue_fn=self._reporter.enqueue,
                capture_messages=self.capture_messages,
                enabled=self._patch_kwargs,
            )
            if patched:
                logger.debug("Auto-patched: %s", patched)

        # Send init event
        self._reporter.enqueue({
            "kind": "sdk_init",
            "ts": time.time(),
            "data": {
                "sdk_version": _VERSION,
                "python_version": platform.python_version(),
                "os": platform.system(),
                "arch": platform.machine(),
                "agent_name": self.agent_name,
            },
        })

    def _enqueue(self, event: Dict[str, Any]) -> None:
        if self._reporter:
            self._reporter.enqueue(event)

    # -- Manual event API --

    def event(self, name: str, data: Optional[Dict[str, Any]] = None) -> None:
        """Send a custom event."""
        ev: Dict[str, Any] = {"kind": "custom_event", "ts": time.time(), "data": {"name": name, **(data or {})}}
        span = get_current_span()
        if span:
            ev["span_id"] = span.id
        self._enqueue(ev)

    def metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Send a numeric metric."""
        ev: Dict[str, Any] = {"kind": "metric", "ts": time.time(), "data": {"name": name, "value": value}}
        if tags:
            ev["data"]["tags"] = tags
        span = get_current_span()
        if span:
            ev["span_id"] = span.id
        self._enqueue(ev)

    def alert(self, message: str, severity: str = "warning", details: Optional[str] = None) -> None:
        """Send an alert."""
        ev: Dict[str, Any] = {"kind": "alert", "ts": time.time(), "data": {"message": message, "severity": severity}}
        if details:
            ev["data"]["details"] = details
        self._enqueue(ev)

    # -- Context managers (forwarded from decorators/session/cron) --

    def session(self, name: str) -> "SessionContext":
        from agentpulse.session import SessionContext
        return SessionContext(name, self._enqueue)

    def cron(self, name: str) -> "CronContext":
        from agentpulse.cron import CronContext
        return CronContext(name, self._enqueue)

    # -- Lifecycle --

    def shutdown(self) -> None:
        """Unpatch all interceptors, flush events, stop reporter."""
        unpatch_all()
        if self._reporter:
            self._reporter.shutdown()

    def flush(self) -> None:
        """Force an immediate flush of queued events."""
        if self._reporter:
            self._reporter._flush()


def init(**kwargs: Any) -> AgentPulseClient:
    """Initialize AgentPulse. Singleton — repeated calls return the existing client."""
    global _client
    if _client is not None:
        return _client
    _client = AgentPulseClient(**kwargs)
    return _client


def shutdown() -> None:
    """Shutdown AgentPulse and restore all patched libraries."""
    global _client
    if _client:
        _client.shutdown()
        _client = None


def get_client() -> Optional[AgentPulseClient]:
    """Return the current client instance, if initialized."""
    return _client
