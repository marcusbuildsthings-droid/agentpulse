"""Auto-detect installed LLM libraries and patch them."""

from __future__ import annotations

import importlib
import logging
import sys
from typing import Any, Callable, Dict, List

from agentpulse.interceptors import anthropic as anthropic_interceptor
from agentpulse.interceptors import langchain as langchain_interceptor
from agentpulse.interceptors import litellm as litellm_interceptor
from agentpulse.interceptors import openai as openai_interceptor

logger = logging.getLogger("agentpulse")

_import_hook_installed = False

# Registry of library module name -> (patch_fn, unpatch_fn)
_INTERCEPTORS: Dict[str, tuple] = {
    "openai": (openai_interceptor.patch, openai_interceptor.unpatch),
    "anthropic": (anthropic_interceptor.patch, anthropic_interceptor.unpatch),
    "litellm": (litellm_interceptor.patch, litellm_interceptor.unpatch),
    "langchain_core": (langchain_interceptor.patch, langchain_interceptor.unpatch),
    "langchain": (langchain_interceptor.patch, langchain_interceptor.unpatch),
}

_patched_libs: List[str] = []


class _AgentPulseImportHook:
    """Meta-path finder that patches LLM libraries when they're imported after init()."""

    def __init__(self, enqueue_fn: Callable, capture_messages: bool, enabled_libs: set):
        self._enqueue_fn = enqueue_fn
        self._capture_messages = capture_messages
        self._enabled_libs = enabled_libs

    def find_module(self, fullname: str, path: Any = None) -> Any:
        # We only care about top-level library imports
        top = fullname.split(".")[0]
        if top in self._enabled_libs and top not in _patched_libs:
            return self
        return None

    def load_module(self, fullname: str) -> Any:
        # Remove ourselves temporarily to avoid recursion
        if self in sys.meta_path:
            sys.meta_path.remove(self)
        try:
            module = importlib.import_module(fullname)
        finally:
            if self not in sys.meta_path:
                sys.meta_path.insert(0, self)

        top = fullname.split(".")[0]
        if top in self._enabled_libs and top not in _patched_libs:
            _try_patch(top, self._enqueue_fn, self._capture_messages)

        return module


def _try_patch(lib: str, enqueue_fn: Callable, capture_messages: bool) -> bool:
    if lib not in _INTERCEPTORS:
        return False
    patch_fn, _ = _INTERCEPTORS[lib]
    try:
        patch_fn(enqueue_fn, capture_messages=capture_messages)
        _patched_libs.append(lib)
        logger.debug("Auto-patched %s", lib)
        return True
    except Exception as exc:
        logger.debug("Failed to patch %s: %s", lib, exc)
        return False


def patch_all(
    enqueue_fn: Callable,
    capture_messages: bool = False,
    enabled: Dict[str, bool] | None = None,
) -> List[str]:
    """Detect and patch all available LLM libraries.

    Args:
        enqueue_fn: Function to call with captured events.
        capture_messages: Whether to capture prompt/response content.
        enabled: Dict of lib_name -> bool to enable/disable specific patches.

    Returns:
        List of library names that were successfully patched.
    """
    global _import_hook_installed

    enabled = enabled or {}
    enabled_libs = set()

    for lib in _INTERCEPTORS:
        if not enabled.get(f"patch_{lib}", True):
            continue
        enabled_libs.add(lib)
        # Patch if already imported
        if lib in sys.modules:
            _try_patch(lib, enqueue_fn, capture_messages)

    # Install import hook for late imports
    remaining = enabled_libs - set(_patched_libs)
    if remaining and not _import_hook_installed:
        hook = _AgentPulseImportHook(enqueue_fn, capture_messages, remaining)
        sys.meta_path.insert(0, hook)
        _import_hook_installed = True
        logger.debug("Import hook installed for: %s", remaining)

    return list(_patched_libs)


def unpatch_all() -> None:
    """Restore all patched libraries to their originals."""
    global _import_hook_installed

    for lib in list(_patched_libs):
        if lib in _INTERCEPTORS:
            _, unpatch_fn = _INTERCEPTORS[lib]
            try:
                unpatch_fn()
            except Exception as exc:
                logger.debug("Failed to unpatch %s: %s", lib, exc)

    _patched_libs.clear()

    # Remove import hooks
    sys.meta_path[:] = [h for h in sys.meta_path if not isinstance(h, _AgentPulseImportHook)]
    _import_hook_installed = False
