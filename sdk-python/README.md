# AgentPulse Python SDK

Lightweight monitoring for indie AI agents. Zero dependencies. Fire-and-forget.

## Install

```bash
pip install agentpulse
```

## Quick Start (Manual)

```python
from agentpulse import pulse

# Initialize with your API key
pulse.init(api_key="ap_...")

# Track sessions
pulse.session_start("main")
pulse.session_message("main", "Hello", role="user")
pulse.session_end("main")

# Report cron jobs
pulse.cron_report("email-check", status="ok", duration_ms=1200)

# Track costs
pulse.cost_event(model="claude-opus-4", tokens_in=5000, tokens_out=1000, cost_usd=0.15)

# Custom metrics
pulse.metric("response_time_ms", 342)

# Heartbeat
pulse.heartbeat()
```

## Auto-Patching (Anthropic SDK)

**NEW in v0.2**: Automatically monitor existing Anthropic SDK usage with zero code changes:

```python
import os
os.environ["AGENTPULSE_API_KEY"] = "ap_..."

# Option 1: Auto-patch on import
os.environ["AGENTPULSE_AUTOPATCH"] = "1"
import anthropic  # <- Automatically patched!

# Option 2: Manual patching
from agentpulse import patch_anthropic
import anthropic
patch_anthropic()  # <- Now all anthropic.messages.create() calls are monitored

# Your existing code works unchanged
client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-3-sonnet-20240229",
    messages=[{"role": "user", "content": "Hello"}]
)
# ^ This call is now automatically tracked in AgentPulse!
```

**What gets tracked:**
- Session creation for each API call
- Token usage (input/output)
- Cost estimation (based on 2026 Anthropic pricing)
- Errors and response times
- Model information

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
