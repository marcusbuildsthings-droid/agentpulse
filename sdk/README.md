# AgentPulse SDK

Zero-config observability for AI agents. Two lines of code → full LLM call tracking with costs, latency, and traces.

## Quick Start

```bash
pip install agentpulse
```

```python
import agentpulse
agentpulse.init()  # That's it — all LLM calls are now tracked

import openai
client = openai.OpenAI()
resp = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}]
)
# → Dashboard shows: model, tokens, cost, latency — automatically
```

## What Gets Captured

With just `agentpulse.init()`, the SDK automatically captures:

- **LLM calls** — model, tokens, latency, cost (OpenAI, Anthropic, LiteLLM)
- **Errors** — failed API calls with error details
- **Streaming** — full metrics even for streamed responses
- **Cost estimates** — built-in pricing for 30+ models

## Structured Tracing

For richer observability, add sessions, agents, and tasks:

```python
import agentpulse
ap = agentpulse.init()

# Group related calls into sessions
with ap.session("daily-email-check") as s:
    result = process_emails()
    s.log("Processed 5 emails")
    s.set_result("success")

# Decorate agents and tasks
@agentpulse.agent(name="email-processor")
class EmailAgent:
    @agentpulse.task(name="classify")
    def classify(self, email):
        return call_llm(email)

# Monitor cron jobs
with ap.cron("nightly-cleanup") as c:
    do_cleanup()
    # Auto-captures: start, end, duration, success/failure
```

## Manual Events

```python
ap.event("memory_snapshot", {"file": "MEMORY.md", "size_kb": 142})
ap.metric("queue_depth", 23)
ap.alert("Cost spike", severity="warning", details="$5.20 in last hour")
```

## Configuration

All via `init()` kwargs or environment variables:

```python
agentpulse.init(
    api_key="ap_...",              # or AGENTPULSE_API_KEY
    agent_name="my-agent",         # or AGENTPULSE_AGENT (default: hostname)
    endpoint="https://...",        # or AGENTPULSE_ENDPOINT
    enabled=True,                  # or AGENTPULSE_ENABLED (kill switch)
    capture_messages=False,        # or AGENTPULSE_CAPTURE_MESSAGES (privacy)
    auto_patch=True,               # or AGENTPULSE_AUTO_PATCH
    debug=False,                   # or AGENTPULSE_DEBUG
    flush_interval=5.0,            # seconds between flushes
    max_queue_size=10_000,         # max buffered events
)
```

## CLI

```bash
agentpulse status   # Check config and connectivity
agentpulse test     # Send a test event
agentpulse costs    # Print the built-in cost table
```

## Design Principles

- **Zero dependencies** — stdlib only (`urllib`, `json`, `threading`, `contextvars`)
- **Never blocks** — all reporting is fire-and-forget via background thread
- **<1ms overhead** — just a timestamp + queue append per LLM call
- **Privacy by default** — prompt/response content not captured unless opted in
- **Unpatchable** — `shutdown()` restores all original library methods

## License

MIT
