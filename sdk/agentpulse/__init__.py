"""AgentPulse — Zero-config agent observability SDK."""

from agentpulse.client import get_client, init, shutdown

__version__ = "0.2.0"
__all__ = [
    "init",
    "shutdown",
    "session",
    "cron",
    "event",
    "metric",
    "alert",
    "agent",
    "task",
    "trace",
]


# Module-level convenience wrappers that delegate to the singleton client

def session(name: str):
    """Context manager for session tracing."""
    c = get_client()
    if c is None:
        raise RuntimeError("Call agentpulse.init() first")
    return c.session(name)


def cron(name: str):
    """Context manager for cron job monitoring."""
    c = get_client()
    if c is None:
        raise RuntimeError("Call agentpulse.init() first")
    return c.cron(name)


def event(name: str, data=None):
    c = get_client()
    if c:
        c.event(name, data)


def metric(name: str, value: float, tags=None):
    c = get_client()
    if c:
        c.metric(name, value, tags)


def alert(message: str, severity: str = "warning", details=None):
    c = get_client()
    if c:
        c.alert(message, severity, details)


# Decorator re-exports
def agent(name: str = "", **kwargs):
    from agentpulse.decorators import agent as _agent
    return _agent(name=name, **kwargs)


def task(name: str = "", **kwargs):
    from agentpulse.decorators import task as _task
    return _task(name=name, **kwargs)


def trace(name: str = "", **kwargs):
    from agentpulse.decorators import trace as _trace
    return _trace(name=name, **kwargs)
