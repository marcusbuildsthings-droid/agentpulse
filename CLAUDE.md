# CLAUDE.md — AgentPulse SDK v2 Build Guide

## What Is This

AgentPulse is an observability SDK for AI agents. You're rebuilding the Python SDK from a dumb HTTP POST wrapper into a zero-config auto-instrumentation library.

**Read first:** `SDK-REDESIGN.md` — the full spec.

## Project Structure

```
sdk-python/
├── agentpulse/           # The package (existing, needs rewrite)
├── tests/                # Create this
├── pyproject.toml        # Existing, update
└── README.md             # Existing, rewrite
```

## Build Order

### Phase 1: Core Interceptors (START HERE)

1. **`agentpulse/context.py`** — Span/trace context using `contextvars`
   - `Span` dataclass: id, parent_id, name, kind, start_time, end_time, metadata, events
   - `_current_span` ContextVar
   - `start_span()`, `end_span()` helpers
   - Must work with both sync and async code

2. **`agentpulse/reporter.py`** — Background batch reporter
   - Daemon thread, flushes every 5s
   - Thread-safe deque, max 10K events
   - gzip compressed POST to `/v1/ingest`
   - Retry with exponential backoff (3 attempts then drop)
   - `atexit` flush registration
   - **Zero dependencies** — use `urllib.request` only

3. **`agentpulse/costs.py`** — Cost lookup table
   - Dict of model → {input_cost_per_1k, output_cost_per_1k}
   - Cover: gpt-4o, gpt-4o-mini, gpt-4-turbo, claude-opus-4, claude-sonnet-4, claude-haiku, etc.
   - `calculate_cost(model, input_tokens, output_tokens) -> float`
   - Fuzzy match on model names (handle "gpt-4o-2024-08-06" etc.)

4. **`agentpulse/interceptors/openai.py`** — OpenAI monkey-patch
   - Patch `openai.resources.chat.completions.Completions.create`
   - Patch async variant `AsyncCompletions.create`
   - Handle streaming (wrap iterator, capture on completion)
   - Capture: model, tokens, latency, cost, error
   - Store original method for `unpatch()`

5. **`agentpulse/interceptors/anthropic.py`** — Anthropic monkey-patch
   - Patch `anthropic.resources.messages.Messages.create`
   - Patch async + streaming variants
   - Same capture pattern as OpenAI

6. **`agentpulse/interceptors/__init__.py`** — Auto-detect and patch orchestrator
   - Check `sys.modules` for installed libraries
   - Register `sys.meta_path` import hook for late imports
   - `patch_all()`, `unpatch_all()`

7. **`agentpulse/client.py`** — Rewrite the main client
   - `init()` → configure + auto-detect + patch + start reporter
   - `shutdown()` → unpatch + flush + stop reporter
   - Keep manual event methods (`event()`, `metric()`, `alert()`)
   - Singleton pattern with module-level `init()`

8. **`agentpulse/__init__.py`** — Clean public API
   - Export: `init`, `shutdown`, `session`, `cron`, `agent`, `task`, `trace`, `event`, `metric`, `alert`

### Phase 2: Structured Tracing

9. **`agentpulse/decorators.py`** — `@agent`, `@task`, `@trace`
   - Create span on entry, close on exit
   - Capture function args/return (configurable)
   - Support sync and async
   - Support class decorators (`@agent` on a class)

10. **`agentpulse/session.py`** — `with ap.session("name")` context manager
    - Creates root span
    - All nested LLM calls + decorated functions attach as children

11. **`agentpulse/cron.py`** — `with ap.cron("job")` context manager
    - Captures start/end/duration/status
    - Auto-sets status="error" on exception

### Phase 3: More Interceptors

12. **`agentpulse/interceptors/litellm.py`**
13. **`agentpulse/interceptors/langchain.py`** — Callback handler approach

## Key Design Rules

- **Zero dependencies for core** — stdlib only (`urllib`, `json`, `threading`, `contextvars`, `gzip`, `atexit`)
- **Never block user code** — all reporting is fire-and-forget
- **<1ms overhead per LLM call** — just timestamp + queue append
- **Privacy by default** — don't capture message content unless `capture_messages=True`
- **Unpatchable** — always store originals, `shutdown()` restores everything
- **Thread-safe** — the reporter and interceptors must handle concurrent access
- **Async-aware** — patch both sync and async variants; use `contextvars` (works with asyncio)

## Testing Strategy

```
tests/
├── test_interceptors/
│   ├── test_openai.py      # Mock openai, verify patching captures events
│   ├── test_anthropic.py   # Mock anthropic, verify patching
│   └── test_detection.py   # Verify auto-detection logic
├── test_reporter.py        # Verify batching, gzip, retry, backoff
├── test_context.py         # Verify span nesting, contextvars
├── test_costs.py           # Verify cost calculations
├── test_decorators.py      # Verify @agent, @task work
├── test_session.py         # Verify session context manager
└── test_integration.py     # End-to-end with mock server
```

Use `pytest`. Mock LLM libraries (don't make real API calls). Test both sync and async paths.

## Config Reference

All via kwargs to `init()` or env vars:

| Param | Env Var | Default | Description |
|-------|---------|---------|-------------|
| `api_key` | `AGENTPULSE_API_KEY` | (required) | API key |
| `agent_name` | `AGENTPULSE_AGENT` | hostname | Agent identifier |
| `endpoint` | `AGENTPULSE_ENDPOINT` | `https://api.agentpulse.dev` | API endpoint |
| `enabled` | `AGENTPULSE_ENABLED` | `true` | Kill switch |
| `capture_messages` | `AGENTPULSE_CAPTURE_MESSAGES` | `false` | Send prompt/response content |
| `auto_patch` | `AGENTPULSE_AUTO_PATCH` | `true` | Auto-detect and patch libraries |
| `flush_interval` | — | `5.0` | Seconds between flushes |
| `max_queue_size` | — | `10000` | Max buffered events |
| `debug` | `AGENTPULSE_DEBUG` | `false` | Verbose stderr logging |

## Existing Code

- `sdk-python/agentpulse/client.py` — current dumb wrapper (rewrite, don't extend)
- `SPEC.md` — original product spec (context only)
- `SECURITY-AUDIT.md` — security considerations for the API
- `api/` — Cloudflare Workers backend (don't touch)
- `dashboard/` — Frontend (don't touch)

## What Success Looks Like

```python
# This should work with ZERO other changes to user code:
import agentpulse
agentpulse.init()

import openai
client = openai.OpenAI()
resp = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}]
)
# → AgentPulse dashboard shows: model, tokens, cost, latency
# → User wrote 2 lines of AgentPulse code
```
