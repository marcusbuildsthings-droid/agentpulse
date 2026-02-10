# AgentPulse Python SDK

Lightweight monitoring for indie AI agents. Zero dependencies. Fire-and-forget.

## Install

```bash
pip install agentpulse
```

## Quick Start

```python
from agentpulse import pulse, init

# Initialize with your API key
init(api_key="ap_...")

# Track sessions
pulse.session_start("main")
pulse.session_event("main", "tool_call", {"tool": "web_search"})
pulse.session_end("main")

# Report cron jobs
pulse.cron_report("email-check", status="ok", duration_ms=1200)
pulse.cron_report("backup", status="error", summary="disk full")

# Track costs
pulse.cost_event(model="claude-opus-4", input_tokens=5000, output_tokens=1000, cost=0.15)

# Monitor memory
pulse.memory_report("MEMORY.md", size_bytes=45000, lines=800)

# Custom metrics
pulse.metric("response_time_ms", 342)

# Alerts
pulse.alert("Cost spike detected", severity="warning", details="$5.20 in last hour")

# Heartbeat
pulse.heartbeat()
```

## How It Works

Events are queued locally and flushed to the AgentPulse API in batches every 10 seconds. Zero blocking. If the API is unreachable, events are retried on the next flush cycle.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `AGENTPULSE_API_KEY` | Your API key |
| `AGENTPULSE_ENDPOINT` | Custom API endpoint |
| `AGENTPULSE_AGENT` | Agent name (defaults to hostname) |

## License

MIT
