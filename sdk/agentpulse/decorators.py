"""Decorators: @agent, @task, @trace — create spans around functions/classes."""

from __future__ import annotations

import asyncio
import functools
import inspect
import time
from contextvars import Token
from typing import Any, Callable, Optional, TypeVar, overload

from agentpulse.client import get_client
from agentpulse.context import Span, _current_span, start_span

F = TypeVar("F", bound=Callable)


def _make_decorator(kind: str, name: str = "", capture_args: bool = False, capture_return: bool = False):
    """Factory for span-creating decorators."""

    def decorator(fn_or_class: Any) -> Any:
        # Class decorator
        if isinstance(fn_or_class, type):
            span_name = name or fn_or_class.__name__
            orig_init = fn_or_class.__init__

            @functools.wraps(orig_init)
            def new_init(self_obj: Any, *args: Any, **kwargs: Any) -> None:
                self_obj._agentpulse_span = start_span(span_name, kind=kind)
                orig_init(self_obj, *args, **kwargs)

            fn_or_class.__init__ = new_init
            return fn_or_class

        # Function decorator
        span_name = name or getattr(fn_or_class, "__name__", str(fn_or_class))

        if inspect.iscoroutinefunction(fn_or_class):

            @functools.wraps(fn_or_class)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                span = start_span(span_name, kind=kind)
                token: Token = _current_span.set(span)
                try:
                    result = await fn_or_class(*args, **kwargs)
                    span.finish(status="ok")
                    _emit_span(span, args if capture_args else None, result if capture_return else None)
                    return result
                except Exception as exc:
                    span.finish(status="error", error=str(exc))
                    _emit_span(span, args if capture_args else None, None)
                    raise
                finally:
                    _current_span.reset(token)

            return async_wrapper
        else:

            @functools.wraps(fn_or_class)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                span = start_span(span_name, kind=kind)
                token: Token = _current_span.set(span)
                try:
                    result = fn_or_class(*args, **kwargs)
                    span.finish(status="ok")
                    _emit_span(span, args if capture_args else None, result if capture_return else None)
                    return result
                except Exception as exc:
                    span.finish(status="error", error=str(exc))
                    _emit_span(span, args if capture_args else None, None)
                    raise
                finally:
                    _current_span.reset(token)

            return sync_wrapper

    return decorator


def _emit_span(span: Span, args: Any, result: Any) -> None:
    """Send the span as an event to the reporter."""
    client = get_client()
    if not client:
        return
    event = {
        "kind": "span_end",
        "ts": time.time(),
        **span.to_dict(),
    }
    if args is not None:
        try:
            event["data"] = {"args": repr(args)[:500]}
        except Exception:
            pass
    if result is not None:
        try:
            event.setdefault("data", {})["result"] = repr(result)[:500]
        except Exception:
            pass
    client._enqueue(event)


# Public decorators

@overload
def agent(fn: F) -> F: ...
@overload
def agent(*, name: str = "", capture_args: bool = False, capture_return: bool = False) -> Callable[[F], F]: ...
def agent(fn: Any = None, *, name: str = "", capture_args: bool = False, capture_return: bool = False) -> Any:
    """Mark a function or class as an agent span."""
    dec = _make_decorator("agent", name=name, capture_args=capture_args, capture_return=capture_return)
    if fn is not None:
        return dec(fn)
    return dec


@overload
def task(fn: F) -> F: ...
@overload
def task(*, name: str = "", capture_args: bool = False, capture_return: bool = False) -> Callable[[F], F]: ...
def task(fn: Any = None, *, name: str = "", capture_args: bool = False, capture_return: bool = False) -> Any:
    """Mark a function as a task span."""
    dec = _make_decorator("task", name=name, capture_args=capture_args, capture_return=capture_return)
    if fn is not None:
        return dec(fn)
    return dec


@overload
def trace(fn: F) -> F: ...
@overload
def trace(*, name: str = "", capture_args: bool = False, capture_return: bool = False) -> Callable[[F], F]: ...
def trace(fn: Any = None, *, name: str = "", capture_args: bool = False, capture_return: bool = False) -> Any:
    """Mark a function as a generic trace span."""
    dec = _make_decorator("trace", name=name, capture_args=capture_args, capture_return=capture_return)
    if fn is not None:
        return dec(fn)
    return dec
