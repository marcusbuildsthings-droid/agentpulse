# AgentPulse SDK v2 — Zero-Config Agent Observability

> **Status:** SPEC — not yet built
> **Date:** 2026-02-13
> **Author:** Marcus (planning), Claude Code (execution)

## The Problem

The current SDK (`agentpulse/client.py`) is a dumb HTTP POST wrapper. Users manually call `pulse.cost_event(model=..., tokens=...)` etc. Nobody will adopt that — it's busywork. Every competitor auto-captures this stuff.

## The Goal

```python
import agentpulse
agentpulse.init()  # That's it. Everything is auto-captured.
```

One line → full observability: LLM calls, token usage, costs, latency, errors, session traces. Zero manual instrumentation.

---

## Competitive Analysis

### How They Do It

| SDK | Pattern | Pros | Cons |
|-----|---------|------|------|
| **AgentOps** | `agentops.init()` → monkey-patches OpenAI/Anthropic + decorators for structure | Closest to our goal; clean DX | Heavy decorator tax for agent/session structure |
| **LangSmith** | `wrap_openai(client)` wrapper + `@traceable` decorator + env-var auto-trace for LangChain | Deep LangChain integration | Requires wrapping clients manually for non-LC use |
| **Langfuse** | `@observe()` decorator + context managers + callback handlers | Flexible 3 modes (decorator/ctx/manual) | Still requires explicit instrumentation |
| **Helicone** | Proxy: change `base_url` to route through their gateway | Zero code change (just URL swap) | Infra dependency; can't capture non-HTTP stuff |
| **OpenTelemetry** | Monkey-patches library functions at import time; zero-code CLI agent | Industry standard; framework-agnostic | Complex; overkill for our use case |

### Key Insight

AgentOps already does what we want — `agentops.init()` auto-patches LLM clients. But they're framework-focused (CrewAI, AutoGen, LangGraph). **Nobody is purpose-built for indie autonomous agents** — the always-on, cron-driven, memory-using agents that run on personal infrastructure.

Our differentiator isn't the SDK pattern (monkey-patching is table stakes). It's **what we capture** (sessions, crons, memory, drift) and **who we serve** (indie devs, not enterprises).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    User's Python Process                 │
│                                                         │
│  agentpulse.init()                                      │
│       │                                                 │
│       ▼                                                 │
│  ┌─────────────┐    ┌──────────────┐                    │
│  │ Auto-Detect │───▶│ Interceptors │                    │
│  │  Framework  │    │              │                    │
│  │             │    │ • openai.*   │──┐                 │
│  │ • OpenAI?   │    │ • anthropic.*│  │                 │
│  │ • Anthropic?│    │ • litellm.*  │  │                 │
│  │ • LangChain?│    │ • (more)     │  │                 │
│  │ • CrewAI?   │    └──────────────┘  │                 │
│  │ • Raw?      │                      │                 │
│  └─────────────┘    ┌──────────────┐  │                 │
│                     │   Session    │  │   ┌───────────┐ │
│  @pulse.trace ─────▶│   Tracker    │◀─┤   │ Event     │ │
│  @pulse.agent ─────▶│              │  └──▶│ Queue     │ │
│  @pulse.task  ─────▶│ • auto-ID    │     │ (in-mem)  │ │
│                     │ • nesting    │     │           │ │
│                     │ • context    │     │ batch +   │ │
│                     └──────────────┘     │ compress  │ │
│                                          └─────┬─────┘ │
│                                                │       │
│                     ┌──────────────┐     ┌─────▼─────┐ │
│                     │ Error Hook   │────▶│ Background │ │
│                     │ (sys.except) │     │  Reporter  │ │
│                     └──────────────┘     │  Thread    │ │
│                                          └─────┬─────┘ │
└────────────────────────────────────────────────┼───────┘
                                                 │ HTTPS POST
                                                 ▼
                                    ┌─────────────────────┐
                                    │  AgentPulse API      │
                                    │  /v1/ingest          │
                                    └─────────────────────┘
```

### Core Components

1. **Auto-Detector** — on `init()`, inspect `sys.modules` to find installed LLM libraries
2. **Interceptors** — monkey-patch LLM client methods to capture calls transparently
3. **Session Tracker** — context-var based trace tree (parent → child spans)
4. **Event Queue** — thread-safe, bounded, batched
5. **Background Reporter** — daemon thread, flushes every N seconds, gzip compressed
6. **Error Hook** — `sys.excepthook` wrapper for unhandled exceptions

---

## API Surface — What Users Write

### Zero-Config (Most Users)

```python
import agentpulse
agentpulse.init()  # Auto-patches all detected LLM libraries

# Just use OpenAI/Anthropic normally — everything is captured
import openai
client = openai.OpenAI()
resp = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}]
)
# ^ AgentPulse auto-captured: model, tokens, latency, cost, request/response

agentpulse.shutdown()  # Flush remaining events (also registered via atexit)
```

### Structured Mode (Power Users)

```python
import agentpulse
ap = agentpulse.init()

# Named sessions for grouping traces
with ap.session("daily-email-check") as s:
    # All LLM calls within this block are tagged to this session
    result = my_agent_function()
    s.log("Processed 5 emails")  # Custom event
    s.set_result("success")

# Decorators for agent/task structure
@ap.agent(name="email-processor")
class EmailAgent:
    @ap.task(name="classify")
    def classify(self, email):
        # LLM call here is auto-captured under this task span
        return classification

# Cron monitoring
with ap.cron("nightly-cleanup") as c:
    do_cleanup()
    # Auto-captures: start_time, end_time, duration, success/failure
```

### Manual Events (Escape Hatch)

```python
# Still works for custom stuff
ap.event("memory_snapshot", {"file": "MEMORY.md", "size_kb": 142})
ap.metric("queue_depth", 23)
ap.alert("Cost spike", severity="warning", details="$5.20 in last hour")
```

---

## Interceptor Design (The Core Innovation)

### Monkey-Patch Strategy

```python
# On init(), for each detected library:

def patch_openai():
    """Wrap openai.ChatCompletion.create and async variant."""
    import openai
    original_create = openai.resources.chat.completions.Completions.create

    def patched_create(self, *args, **kwargs):
        start = time.monotonic()
        try:
            response = original_create(self, *args, **kwargs)
            elapsed_ms = (time.monotonic() - start) * 1000
            _capture_llm_event(
                provider="openai",
                model=kwargs.get("model", "unknown"),
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
                latency_ms=elapsed_ms,
                messages=kwargs.get("messages"),  # optionally capture (configurable)
                response_preview=response.choices[0].message.content[:200],
                status="success",
            )
            return response
        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            _capture_llm_event(
                provider="openai",
                model=kwargs.get("model", "unknown"),
                latency_ms=elapsed_ms,
                status="error",
                error=str(e),
            )
            raise

    openai.resources.chat.completions.Completions.create = patched_create
    # Also patch: async, streaming, embeddings, images
```

### What Gets Patched

| Library | Methods | Auto-Captured |
|---------|---------|---------------|
| `openai` | `chat.completions.create`, `completions.create`, `embeddings.create` | model, tokens, cost, latency, errors |
| `anthropic` | `messages.create`, `messages.stream` | model, tokens, cost, latency, errors |
| `litellm` | `completion`, `acompletion` | model, tokens, cost, latency (litellm already normalizes) |
| `cohere` | `chat`, `generate` | model, tokens, latency |
| `google.generativeai` | `generate_content` | model, tokens, latency |

### Streaming Support

Streaming is tricky — tokens aren't known until stream completes. Approach:

```python
def patched_create_stream(self, *args, **kwargs):
    if kwargs.get("stream"):
        return StreamInterceptor(original_create(self, *args, **kwargs), kwargs)
    return patched_create(self, *args, **kwargs)

class StreamInterceptor:
    """Wraps a streaming response, captures metrics on completion."""
    def __init__(self, stream, kwargs):
        self._stream = stream
        self._kwargs = kwargs
        self._chunks = []
        self._start = time.monotonic()

    def __iter__(self):
        for chunk in self._stream:
            self._chunks.append(chunk)
            yield chunk
        # Stream complete — now capture
        self._report()

    def _report(self):
        # Reconstruct usage from final chunk or count tokens manually
        ...
```

### Cost Calculation

Maintain a built-in cost table (updated periodically):

```python
COST_PER_1K = {
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "claude-opus-4": {"input": 0.015, "output": 0.075},
    "claude-sonnet-4": {"input": 0.003, "output": 0.015},
    # ... etc
}
```

Ship in package, allow user override, auto-update via API check (weekly).

---

## Framework Integrations

### Tier 1: Auto-Detect (Zero Config)

These work with just `agentpulse.init()`:

- **Raw OpenAI SDK** — monkey-patch `openai.*`
- **Raw Anthropic SDK** — monkey-patch `anthropic.*`
- **LiteLLM** — monkey-patch `litellm.completion`

### Tier 2: Light Integration (Import Hook)

These need the framework to be detected + specific callbacks injected:

- **LangChain/LangGraph** — inject callback handler via `set_handler`
- **CrewAI** — hook into CrewAI's event system
- **OpenAI Agents SDK** — trace handoffs and tool calls

### Tier 3: Explicit (User Opts In)

- **OpenClaw/Clawdbot** — provide middleware hook for the gateway
- **Claude Code CLI** — parse stdout/stderr for token usage (best-effort)
- **Custom frameworks** — decorators and context managers

### Detection Logic

```python
def _detect_and_patch():
    patches = []
    if "openai" in sys.modules:
        patches.append(patch_openai())
    if "anthropic" in sys.modules:
        patches.append(patch_anthropic())
    if "litellm" in sys.modules:
        patches.append(patch_litellm())
    if "langchain" in sys.modules or "langchain_core" in sys.modules:
        patches.append(patch_langchain())
    if "crewai" in sys.modules:
        patches.append(patch_crewai())
    return patches
```

**Important:** Also register an import hook (`sys.meta_path`) so if a library is imported *after* `init()`, we still patch it.

---

## Session & Trace Context

Use `contextvars` for automatic parent-child span tracking:

```python
_current_span: ContextVar[Optional[Span]] = ContextVar("agentpulse_span", default=None)

class Span:
    id: str          # uuid
    parent_id: str   # parent span id (None for root)
    name: str
    kind: str        # "session", "agent", "task", "llm_call"
    start_time: float
    end_time: float
    metadata: dict
    events: list     # child events
```

LLM calls automatically attach to the current span. If no span exists, they attach to a default "unscoped" trace.

---

## Background Reporter

```python
class Reporter:
    """Batched, compressed, non-blocking event sender."""

    def __init__(self, endpoint, api_key, flush_interval=5.0, batch_size=100):
        self._queue = collections.deque(maxlen=10_000)
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while True:
            time.sleep(self._flush_interval)
            self._flush()

    def _flush(self):
        with self._lock:
            batch = list(self._queue)
            self._queue.clear()
        if not batch:
            return
        payload = gzip.compress(json.dumps(batch).encode())
        # POST to /v1/ingest with Content-Encoding: gzip
        # Retry with exponential backoff on failure
        # Drop after 3 retries (don't block the agent)
```

### Design Principles
- **Never block the user's code** — all reporting is fire-and-forget
- **Graceful degradation** — if API is down, buffer up to 10K events, then drop oldest
- **Low overhead** — target <1ms added latency per LLM call
- **atexit flush** — best-effort flush on process exit

---

## What Gets Auto-Captured vs Manual

### Auto-Captured (Zero Config)
| Data | Source |
|------|--------|
| LLM call model, tokens, latency | Interceptor |
| LLM call cost (estimated) | Cost table |
| LLM errors/retries | Interceptor |
| Streaming completion metrics | Stream interceptor |
| Process start/stop | init/shutdown hooks |
| Unhandled exceptions | sys.excepthook |
| Python version, OS, library versions | init() fingerprint |

### Manual (Decorators/Context Managers)
| Data | How |
|------|-----|
| Session boundaries | `with ap.session("name")` |
| Agent/task hierarchy | `@ap.agent`, `@ap.task` |
| Cron job monitoring | `with ap.cron("job")` |
| Custom events/metrics | `ap.event()`, `ap.metric()` |
| Memory file tracking | `ap.memory_report()` |
| Alerts | `ap.alert()` |
| User/session metadata | `ap.set_metadata()` |

---

## Configuration

```python
agentpulse.init(
    # Required (or set AGENTPULSE_API_KEY env var)
    api_key="ap_...",

    # Optional
    agent_name="marcus",          # default: hostname
    endpoint="https://...",       # default: api.agentpulse.dev
    enabled=True,                 # kill switch
    debug=False,                  # verbose logging to stderr

    # Privacy
    capture_messages=False,       # don't send prompt/response content (default: off)
    capture_metadata=True,        # capture model, tokens, cost (default: on)

    # Performance
    flush_interval=5.0,           # seconds between flushes
    max_queue_size=10_000,        # max buffered events
    max_batch_size=100,           # max events per API call

    # Framework control
    auto_patch=True,              # auto-detect and patch libraries
    patch_openai=True,            # granular control
    patch_anthropic=True,
    patch_litellm=True,

    # Cost
    cost_table_override={},       # override built-in costs
)
```

All config also readable from env vars: `AGENTPULSE_API_KEY`, `AGENTPULSE_AGENT`, `AGENTPULSE_CAPTURE_MESSAGES`, etc.

---

## Package Structure

```
agentpulse/
├── __init__.py              # init(), shutdown(), module-level API
├── client.py                # AgentPulse client class
├── config.py                # Configuration handling
├── context.py               # Span/trace context (contextvars)
├── reporter.py              # Background batch reporter
├── costs.py                 # Cost table + calculator
├── interceptors/
│   ├── __init__.py          # Auto-detect + patch orchestrator
│   ├── openai.py            # OpenAI monkey-patches
│   ├── anthropic.py         # Anthropic monkey-patches
│   ├── litellm.py           # LiteLLM monkey-patches
│   ├── langchain.py         # LangChain callback handler
│   └── crewai.py            # CrewAI integration
├── decorators.py            # @agent, @task, @trace decorators
├── session.py               # Session context manager
├── cron.py                  # Cron monitoring context manager
└── _version.py              # Version string
```

---

## MVP Scope (What Ships First)

### Phase 1: Core (Week 1-2)
- [ ] `agentpulse.init()` with auto-patch for `openai` and `anthropic`
- [ ] Background reporter with batching and gzip
- [ ] Auto-capture: model, tokens, latency, cost, errors
- [ ] `contextvars`-based span tracking
- [ ] Streaming support
- [ ] `atexit` flush
- [ ] Env var configuration
- [ ] Zero dependencies (stdlib only for core)

### Phase 2: Structure (Week 3)
- [ ] `@ap.agent`, `@ap.task`, `@ap.trace` decorators
- [ ] `with ap.session()` context manager
- [ ] `with ap.cron()` context manager
- [ ] `ap.event()`, `ap.metric()`, `ap.alert()` manual API
- [ ] Cost table with 20+ models

### Phase 3: Integrations (Week 4)
- [ ] LiteLLM interceptor
- [ ] LangChain callback handler
- [ ] Import hook for late-loaded libraries
- [ ] `capture_messages` privacy mode
- [ ] Retry/backoff in reporter

### Phase 4: Polish (Week 5)
- [ ] PyPI publish (`pip install agentpulse`)
- [ ] Comprehensive tests
- [ ] README with examples
- [ ] Dogfood with OpenClaw/Marcus

---

## Monetization Angle

### Why People Pay

The SDK is free and open-source. The **dashboard** is the product:

1. **Time savings** — "My agent burned $12 last night on a loop" → cost alerts catch this in minutes, not hours
2. **Session replay** — "What did my agent actually do at 3am?" → full trace tree
3. **Cron reliability** — "Did my email checker actually run?" → miss detection
4. **Peace of mind** — green dashboard = agent is healthy, go live your life

### Free Tier = Adoption Funnel
- Free: 1 agent, 10K events/mo, 7-day retention
- Pro ($15/mo): Unlimited agents, 500K events, 90-day retention, alerts
- The SDK captures value immediately; the dashboard makes it visible; retention makes it sticky

### Lock-in Without Lock-in
- SDK is MIT, backend API is simple REST — users can self-host
- But convenience wins: $15/mo is nothing vs running your own infra
- The moat is the dashboard UX + alert intelligence, not the protocol

---

## API Contract (Backend)

### POST /v1/ingest

```json
{
  "agent": "marcus",
  "sdk_version": "0.2.0",
  "events": [
    {
      "kind": "llm_call",
      "ts": 1707974654.123,
      "span_id": "abc123",
      "parent_span_id": "def456",
      "session": "daily-email",
      "data": {
        "provider": "openai",
        "model": "gpt-4o",
        "input_tokens": 150,
        "output_tokens": 89,
        "latency_ms": 1234,
        "cost_usd": 0.0012,
        "status": "success",
        "streaming": false
      }
    },
    {
      "kind": "span_start",
      "ts": 1707974650.0,
      "span_id": "def456",
      "data": {
        "name": "classify-email",
        "span_kind": "task"
      }
    }
  ]
}
```

The backend schema needs to evolve to support span trees, but that's a backend concern — the SDK just ships structured events.

---

## Open Questions

1. **Should we capture prompts/responses by default?** Current lean: NO (privacy). Opt-in via `capture_messages=True`.
2. **How to handle async?** Need to patch both sync and async variants of every LLM client method.
3. **Token counting for streaming?** Some providers don't include usage in stream chunks. May need tiktoken as optional dep.
4. **Import hook reliability?** `sys.meta_path` hooks can be fragile. Fallback: user calls `agentpulse.patch()` after imports.
5. **Cost table freshness?** Ship baked-in, check API for updates weekly, allow override.
