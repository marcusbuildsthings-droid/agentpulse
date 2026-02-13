"""Tests for session context manager."""

from agentpulse.context import _current_span, get_current_span
from agentpulse.session import SessionContext


def test_session_creates_span():
    _current_span.set(None)  # Clean state
    events = []
    with SessionContext("test-session", events.append) as s:
        assert get_current_span() is not None
        assert s.span_id is not None
        s.log("hello")
        s.set_result("success")

    assert get_current_span() is None
    assert len(events) == 2  # span_start + span_end
    assert events[0]["kind"] == "span_start"
    # span_end event has kind from span.to_dict() which is "session"
    assert events[1]["status"] == "success"


def test_session_captures_error():
    events = []
    try:
        with SessionContext("fail-session", events.append):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert events[1]["status"] == "error"
    assert "boom" in events[1]["error"]


def test_session_log():
    events = []
    with SessionContext("log-session", events.append) as s:
        s.log("step 1", count=5)
        s.log("step 2")

    end_event = events[1]
    logs = end_event["data"]["logs"]
    assert len(logs) == 2
    assert logs[0]["message"] == "step 1"
    assert logs[0]["count"] == 5
