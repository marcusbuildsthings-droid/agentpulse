"""LangChain interceptor — callback handler approach."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from agentpulse.context import get_current_span
from agentpulse.costs import calculate_cost

logger = logging.getLogger("agentpulse")

_patched = False
_enqueue_fn: Any = None
_capture_messages = False


class AgentPulseCallbackHandler:
    """LangChain callback handler that captures LLM calls."""

    def __init__(self, enqueue_fn: Any, capture_messages: bool = False):
        self._enqueue = enqueue_fn
        self._capture_messages = capture_messages
        self._starts: Dict[str, float] = {}

    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str],
        *, run_id: UUID, **kwargs: Any,
    ) -> None:
        self._starts[str(run_id)] = time.monotonic()

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        start = self._starts.pop(str(run_id), time.monotonic())
        elapsed_ms = (time.monotonic() - start) * 1000

        # Extract from LangChain LLMResult
        model = "unknown"
        input_tokens = 0
        output_tokens = 0

        if hasattr(response, "llm_output") and response.llm_output:
            llm_out = response.llm_output
            model = llm_out.get("model_name", "unknown")
            usage = llm_out.get("token_usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

        cost = calculate_cost(model, input_tokens, output_tokens)
        span = get_current_span()

        event: dict = {
            "kind": "llm_call", "ts": time.time(),
            "data": {
                "provider": "langchain", "model": model,
                "input_tokens": input_tokens, "output_tokens": output_tokens,
                "latency_ms": round(elapsed_ms, 2), "status": "success",
            },
        }
        if cost is not None:
            event["data"]["cost_usd"] = round(cost, 6)
        if span:
            event["span_id"] = span.id
        if self._enqueue:
            self._enqueue(event)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        start = self._starts.pop(str(run_id), time.monotonic())
        elapsed_ms = (time.monotonic() - start) * 1000
        span = get_current_span()
        event: dict = {
            "kind": "llm_call", "ts": time.time(),
            "data": {
                "provider": "langchain", "model": "unknown",
                "latency_ms": round(elapsed_ms, 2), "status": "error", "error": str(error),
            },
        }
        if span:
            event["span_id"] = span.id
        if self._enqueue:
            self._enqueue(event)


def patch(enqueue_fn: Any, capture_messages: bool = False) -> None:
    global _patched, _enqueue_fn, _capture_messages
    if _patched:
        return
    try:
        from langchain_core.callbacks import manager as cb_manager
    except ImportError:
        try:
            from langchain.callbacks import manager as cb_manager
        except ImportError:
            logger.debug("langchain not installed, skipping")
            return

    _enqueue_fn = enqueue_fn
    _capture_messages = capture_messages

    handler = AgentPulseCallbackHandler(enqueue_fn, capture_messages)

    # Try to add to global callbacks
    try:
        if hasattr(cb_manager, "configure"):
            # LangChain >=0.1: use global handler registration
            from langchain_core.globals import set_llm_cache  # verify import works
        # Fallback: store for manual injection
    except Exception:
        pass

    # Store handler for users to manually add if auto-injection fails
    AgentPulseCallbackHandler._instance = handler  # type: ignore[attr-defined]
    _patched = True
    logger.debug("Patched langchain (callback handler ready)")


def unpatch() -> None:
    global _patched
    _patched = False


def get_handler() -> Optional[AgentPulseCallbackHandler]:
    """Get the callback handler instance for manual injection into LangChain."""
    return getattr(AgentPulseCallbackHandler, "_instance", None)
