"""Session context manager — groups nested LLM calls + spans under a root."""

from __future__ import annotations

import time
from contextvars import Token
from typing import Any, Callable, Dict, Optional

from agentpulse.context import Span, _current_span, start_span


class SessionContext:
    """Usage: `with ap.session("name") as s: ...`"""

    def __init__(self, name: str, enqueue_fn: Callable) -> None:
        self._name = name
        self._enqueue = enqueue_fn
        self._span: Optional[Span] = None
        self._token: Optional[Token] = None
        self._result: Optional[str] = None
        self._logs: list[Dict[str, Any]] = []

    def __enter__(self) -> "SessionContext":
        from agentpulse.context import Span
        # Manually create span and set context (don't use start_span which also sets)
        parent = _current_span.get()
        self._span = Span(
            name=self._name,
            kind="session",
            parent_id=parent.id if parent else None,
        )
        self._token = _current_span.set(self._span)
        self._enqueue({
            "kind": "span_start",
            "ts": time.time(),
            "span_id": self._span.id,
            "data": {"name": self._name, "span_kind": "session"},
        })
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._span:
            if exc_type:
                self._span.finish(status="error", error=str(exc_val))
            else:
                self._span.finish(status=self._result or "ok")
            self._enqueue({
                "kind": "span_end",
                "ts": time.time(),
                **self._span.to_dict(),
                "data": {
                    "name": self._name,
                    "span_kind": "session",
                    "logs": self._logs if self._logs else None,
                },
            })
        if self._token is not None:
            _current_span.reset(self._token)

    def log(self, message: str, **data: Any) -> None:
        """Attach a log entry to this session."""
        entry = {"ts": time.time(), "message": message, **data}
        self._logs.append(entry)
        if self._span:
            self._span.events.append(entry)

    def set_result(self, result: str) -> None:
        """Set the session result status (e.g., 'success', 'partial')."""
        self._result = result

    @property
    def span_id(self) -> Optional[str]:
        return self._span.id if self._span else None

    # Async support
    async def __aenter__(self) -> "SessionContext":
        return self.__enter__()

    async def __aexit__(self, *args: Any) -> None:
        self.__exit__(*args)
