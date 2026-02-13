"""Tests for span/trace context."""

import asyncio

from agentpulse.context import Span, _current_span, end_span, get_current_span, start_span


def test_span_creation():
    s = Span(name="test", kind="trace")
    assert s.name == "test"
    assert s.kind == "trace"
    assert s.id
    assert s.parent_id is None
    assert s.end_time is None
    assert s.status == "ok"


def test_span_finish():
    s = Span(name="test", kind="trace")
    s.finish()
    assert s.end_time is not None
    assert s.duration_ms is not None
    assert s.duration_ms >= 0


def test_span_finish_error():
    s = Span(name="test", kind="trace")
    s.finish(status="error", error="boom")
    assert s.status == "error"
    assert s.error == "boom"


def test_span_to_dict():
    s = Span(name="test", kind="agent", metadata={"k": "v"})
    s.finish()
    d = s.to_dict()
    assert d["name"] == "test"
    assert d["kind"] == "agent"
    assert d["metadata"] == {"k": "v"}
    assert "duration_ms" in d


def test_start_end_span():
    assert get_current_span() is None
    s = start_span("root", kind="session")
    assert get_current_span() is s
    end_span(s)
    assert get_current_span() is None


def test_nested_spans():
    parent = start_span("parent", kind="session")
    token_p = _current_span.set(parent)

    child = start_span("child", kind="task")
    assert child.parent_id == parent.id

    end_span(child)
    _current_span.reset(token_p)
    _current_span.set(None)


def test_span_context_isolation():
    """Verify contextvars work across threads (basic check)."""
    import threading

    results = []

    def worker():
        assert get_current_span() is None
        s = start_span("thread-span", kind="trace")
        results.append(s.name)
        end_span(s)

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert results == ["thread-span"]
    assert get_current_span() is None
