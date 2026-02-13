"""LiteLLM interceptor — monkey-patches litellm.completion and acompletion."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from agentpulse.context import get_current_span
from agentpulse.costs import calculate_cost

logger = logging.getLogger("agentpulse")

_original_completion: Any = None
_original_acompletion: Any = None
_patched = False
_capture_messages = False
_enqueue_fn: Any = None


def _build_event(
    *, model: str, start: float, input_tokens: int = 0, output_tokens: int = 0,
    status: str = "success", error: Optional[str] = None, streaming: bool = False,
) -> dict:
    elapsed_ms = (time.monotonic() - start) * 1000
    cost = calculate_cost(model, input_tokens, output_tokens)
    span = get_current_span()
    event: dict = {
        "kind": "llm_call", "ts": time.time(),
        "data": {
            "provider": "litellm", "model": model,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "latency_ms": round(elapsed_ms, 2), "status": status, "streaming": streaming,
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
    return event


def patch(enqueue_fn: Any, capture_messages: bool = False) -> None:
    global _original_completion, _original_acompletion, _patched, _capture_messages, _enqueue_fn
    if _patched:
        return
    try:
        import litellm
    except ImportError:
        return

    _enqueue_fn = enqueue_fn
    _capture_messages = capture_messages
    _original_completion = litellm.completion

    def patched_completion(*args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        model = kwargs.get("model", args[0] if args else "unknown")
        try:
            response = _original_completion(*args, **kwargs)
        except Exception as exc:
            if _enqueue_fn:
                _enqueue_fn(_build_event(model=model, start=start, status="error", error=str(exc)))
            raise
        usage = getattr(response, "usage", None)
        inp = getattr(usage, "prompt_tokens", 0) or 0
        out = getattr(usage, "completion_tokens", 0) or 0
        if _enqueue_fn:
            _enqueue_fn(_build_event(model=model, start=start, input_tokens=inp, output_tokens=out))
        return response

    litellm.completion = patched_completion

    if hasattr(litellm, "acompletion"):
        _original_acompletion = litellm.acompletion

        async def patched_acompletion(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            model = kwargs.get("model", args[0] if args else "unknown")
            try:
                response = await _original_acompletion(*args, **kwargs)
            except Exception as exc:
                if _enqueue_fn:
                    _enqueue_fn(_build_event(model=model, start=start, status="error", error=str(exc)))
                raise
            usage = getattr(response, "usage", None)
            inp = getattr(usage, "prompt_tokens", 0) or 0
            out = getattr(usage, "completion_tokens", 0) or 0
            if _enqueue_fn:
                _enqueue_fn(_build_event(model=model, start=start, input_tokens=inp, output_tokens=out))
            return response

        litellm.acompletion = patched_acompletion

    _patched = True
    logger.debug("Patched litellm")


def unpatch() -> None:
    global _patched
    if not _patched:
        return
    try:
        import litellm
        if _original_completion:
            litellm.completion = _original_completion
        if _original_acompletion:
            litellm.acompletion = _original_acompletion
    except ImportError:
        pass
    _patched = False
