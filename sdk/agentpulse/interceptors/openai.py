"""OpenAI interceptor — monkey-patches chat completions (sync + async + streaming)."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from agentpulse.context import get_current_span
from agentpulse.costs import calculate_cost

logger = logging.getLogger("agentpulse")

_original_create: Any = None
_original_async_create: Any = None
_patched = False
_capture_messages = False
_enqueue_fn: Any = None


def _build_event(
    *,
    model: str,
    start: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    status: str = "success",
    error: Optional[str] = None,
    streaming: bool = False,
    messages: Any = None,
    response_content: Optional[str] = None,
) -> dict:
    elapsed_ms = (time.monotonic() - start) * 1000 if start else 0
    cost = calculate_cost(model, input_tokens, output_tokens)
    span = get_current_span()

    event: dict = {
        "kind": "llm_call",
        "ts": time.time(),
        "data": {
            "provider": "openai",
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": round(elapsed_ms, 2),
            "status": status,
            "streaming": streaming,
        },
    }
    if cost is not None:
        event["data"]["cost_usd"] = round(cost, 6)
    if error:
        event["data"]["error"] = error
    if span:
        event["span_id"] = span.id
        if span.parent_id:
            event["parent_span_id"] = span.parent_id
    if _capture_messages and messages:
        event["data"]["messages"] = messages
    if _capture_messages and response_content:
        event["data"]["response_preview"] = response_content[:500]
    return event


class _SyncStreamWrapper:
    """Wraps a sync streaming response to capture metrics on completion."""

    def __init__(self, stream: Any, model: str, start: float, messages: Any = None):
        self._stream = stream
        self._model = model
        self._start = start
        self._messages = messages
        self._chunks: list = []

    def __iter__(self):
        try:
            for chunk in self._stream:
                self._chunks.append(chunk)
                yield chunk
        finally:
            self._report()

    def __enter__(self):
        if hasattr(self._stream, "__enter__"):
            self._stream.__enter__()
        return self

    def __exit__(self, *args):
        if hasattr(self._stream, "__exit__"):
            self._stream.__exit__(*args)

    def _report(self):
        input_tokens = 0
        output_tokens = 0
        content_parts: list[str] = []
        # Try to get usage from final chunk
        for chunk in reversed(self._chunks):
            if hasattr(chunk, "usage") and chunk.usage:
                input_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0
                break
        # Collect content
        for chunk in self._chunks:
            if hasattr(chunk, "choices") and chunk.choices:
                delta = getattr(chunk.choices[0], "delta", None)
                if delta and getattr(delta, "content", None):
                    content_parts.append(delta.content)

        event = _build_event(
            model=self._model,
            start=self._start,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            streaming=True,
            messages=self._messages,
            response_content="".join(content_parts) if content_parts else None,
        )
        if _enqueue_fn:
            _enqueue_fn(event)


class _AsyncStreamWrapper:
    """Wraps an async streaming response."""

    def __init__(self, stream: Any, model: str, start: float, messages: Any = None):
        self._stream = stream
        self._model = model
        self._start = start
        self._messages = messages
        self._chunks: list = []

    async def __aiter__(self):
        try:
            async for chunk in self._stream:
                self._chunks.append(chunk)
                yield chunk
        finally:
            self._report()

    async def __aenter__(self):
        if hasattr(self._stream, "__aenter__"):
            await self._stream.__aenter__()
        return self

    async def __aexit__(self, *args):
        if hasattr(self._stream, "__aexit__"):
            await self._stream.__aexit__(*args)

    def _report(self):
        input_tokens = 0
        output_tokens = 0
        for chunk in reversed(self._chunks):
            if hasattr(chunk, "usage") and chunk.usage:
                input_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
                output_tokens = getattr(chunk.usage, "completion_tokens", 0) or 0
                break
        event = _build_event(
            model=self._model,
            start=self._start,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            streaming=True,
            messages=self._messages,
        )
        if _enqueue_fn:
            _enqueue_fn(event)


def patch(enqueue_fn: Any, capture_messages: bool = False) -> None:
    """Monkey-patch OpenAI chat completions."""
    global _original_create, _original_async_create, _patched, _capture_messages, _enqueue_fn

    if _patched:
        return

    try:
        import openai.resources.chat.completions as chat_mod
    except ImportError:
        logger.debug("openai not installed, skipping patch")
        return

    _enqueue_fn = enqueue_fn
    _capture_messages = capture_messages

    # Sync — detect conflicts
    _original_create = chat_mod.Completions.create
    if getattr(_original_create, '_agentpulse_patched', False):
        logger.warning("OpenAI Completions.create already patched by AgentPulse, skipping")
        return

    def patched_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        model = kwargs.get("model", "unknown")
        messages = kwargs.get("messages")
        stream = kwargs.get("stream", False)

        try:
            response = _original_create(self, *args, **kwargs)
        except Exception as exc:
            event = _build_event(model=model, start=start, status="error", error=str(exc), messages=messages)
            if _enqueue_fn:
                _enqueue_fn(event)
            raise

        if stream:
            return _SyncStreamWrapper(response, model, start, messages)

        # Non-streaming
        input_tokens = getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0
        output_tokens = getattr(getattr(response, "usage", None), "completion_tokens", 0) or 0
        content = None
        if hasattr(response, "choices") and response.choices:
            msg = getattr(response.choices[0], "message", None)
            if msg:
                content = getattr(msg, "content", None)

        event = _build_event(
            model=model, start=start, input_tokens=input_tokens, output_tokens=output_tokens,
            messages=messages, response_content=content,
        )
        if _enqueue_fn:
            _enqueue_fn(event)
        return response

    patched_create._agentpulse_patched = True  # type: ignore[attr-defined]
    chat_mod.Completions.create = patched_create  # type: ignore[assignment]

    # Async
    try:
        _original_async_create = chat_mod.AsyncCompletions.create

        async def patched_async_create(self: Any, *args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            model = kwargs.get("model", "unknown")
            messages = kwargs.get("messages")
            stream = kwargs.get("stream", False)

            try:
                response = await _original_async_create(self, *args, **kwargs)
            except Exception as exc:
                event = _build_event(model=model, start=start, status="error", error=str(exc), messages=messages)
                if _enqueue_fn:
                    _enqueue_fn(event)
                raise

            if stream:
                return _AsyncStreamWrapper(response, model, start, messages)

            input_tokens = getattr(getattr(response, "usage", None), "prompt_tokens", 0) or 0
            output_tokens = getattr(getattr(response, "usage", None), "completion_tokens", 0) or 0
            content = None
            if hasattr(response, "choices") and response.choices:
                msg = getattr(response.choices[0], "message", None)
                if msg:
                    content = getattr(msg, "content", None)

            event = _build_event(
                model=model, start=start, input_tokens=input_tokens, output_tokens=output_tokens,
                messages=messages, response_content=content,
            )
            if _enqueue_fn:
                _enqueue_fn(event)
            return response

        patched_async_create._agentpulse_patched = True  # type: ignore[attr-defined]
        chat_mod.AsyncCompletions.create = patched_async_create  # type: ignore[assignment]
    except AttributeError:
        pass  # No async completions in this version

    _patched = True
    logger.debug("Patched openai")


def unpatch() -> None:
    """Restore original OpenAI methods."""
    global _patched
    if not _patched:
        return
    try:
        import openai.resources.chat.completions as chat_mod

        if _original_create:
            chat_mod.Completions.create = _original_create  # type: ignore[assignment]
        if _original_async_create:
            chat_mod.AsyncCompletions.create = _original_async_create  # type: ignore[assignment]
    except ImportError:
        pass
    _patched = False
