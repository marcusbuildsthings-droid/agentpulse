"""Span/trace context using contextvars for automatic parent-child tracking."""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_current_span: ContextVar[Optional["Span"]] = ContextVar("agentpulse_span", default=None)


@dataclass
class Span:
    """A single unit of work in a trace tree."""

    name: str
    kind: str  # "session", "agent", "task", "llm_call", "cron", "trace"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "ok"
    error: Optional[str] = None

    def finish(self, status: str = "ok", error: Optional[str] = None) -> None:
        self.end_time = time.time()
        self.status = status
        if error:
            self.error = error

    @property
    def duration_ms(self) -> Optional[float]:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "span_id": self.id,
            "name": self.name,
            "kind": self.kind,
            "start_time": self.start_time,
            "status": self.status,
        }
        if self.parent_id:
            d["parent_span_id"] = self.parent_id
        if self.end_time is not None:
            d["end_time"] = self.end_time
            d["duration_ms"] = self.duration_ms
        if self.metadata:
            d["metadata"] = self.metadata
        if self.events:
            d["events"] = self.events
        if self.error:
            d["error"] = self.error
        return d


def get_current_span() -> Optional[Span]:
    """Return the current active span, if any."""
    return _current_span.get()


def start_span(name: str, kind: str = "trace", metadata: Optional[Dict[str, Any]] = None) -> Span:
    """Create and activate a new span, parenting to the current span if one exists."""
    parent = _current_span.get()
    span = Span(
        name=name,
        kind=kind,
        parent_id=parent.id if parent else None,
        metadata=metadata or {},
    )
    _current_span.set(span)
    return span


def end_span(span: Span, status: str = "ok", error: Optional[str] = None) -> None:
    """Finish a span and restore the parent as current."""
    span.finish(status=status, error=error)
    # We don't track parent objects (just IDs), so reset to None.
    # The context manager / decorator is responsible for token restore.
    _current_span.set(None)
