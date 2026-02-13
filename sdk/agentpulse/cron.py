"""Cron monitoring context manager — captures start/end/duration/status."""

from __future__ import annotations

import time
from contextvars import Token
from typing import Any, Callable, Optional

from agentpulse.context import Span, _current_span, start_span


class CronContext:
    """Usage: `with ap.cron("nightly-cleanup") as c: ...`"""

    def __init__(self, name: str, enqueue_fn: Callable) -> None:
        self._name = name
        self._enqueue = enqueue_fn
        self._span: Optional[Span] = None
        self._token: Optional[Token] = None

    def __enter__(self) -> "CronContext":
        from agentpulse.context import Span
        parent = _current_span.get()
        self._span = Span(
            name=self._name,
            kind="cron",
            parent_id=parent.id if parent else None,
        )
        self._token = _current_span.set(self._span)
        self._enqueue({
            "kind": "span_start",
            "ts": time.time(),
            "span_id": self._span.id,
            "data": {"name": self._name, "span_kind": "cron"},
        })
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._span:
            if exc_type:
                self._span.finish(status="error", error=str(exc_val))
            else:
                self._span.finish(status="ok")
            self._enqueue({
                "kind": "span_end",
                "ts": time.time(),
                **self._span.to_dict(),
                "data": {"name": self._name, "span_kind": "cron"},
            })
        if self._token is not None:
            _current_span.reset(self._token)

    @property
    def span_id(self) -> Optional[str]:
        return self._span.id if self._span else None

    async def __aenter__(self) -> "CronContext":
        return self.__enter__()

    async def __aexit__(self, *args: Any) -> None:
        self.__exit__(*args)
