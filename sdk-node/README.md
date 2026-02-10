# agentpulse

Lightweight monitoring SDK for AI agents. Zero dependencies. Fire-and-forget.

## Install

```bash
npm install agentpulse
```

## Quick Start

```typescript
import { init, pulse } from 'agentpulse';

init({ apiKey: 'ap_your_key' });

// Track sessions
pulse.sessionStart('main');
pulse.sessionEnd('main');

// Report costs
pulse.costEvent({ model: 'claude-opus-4', inputTokens: 5000, cost: 0.15 });

// Monitor cron jobs
pulse.cronReport('backup', { status: 'ok', durationMs: 3400 });

// Custom metrics
pulse.metric('queue_depth', 42);

// Alerts
pulse.alert('High cost', 'warning', 'Daily spend exceeded $5');

// Memory health
pulse.memoryReport({ file: 'MEMORY.md', sizeBytes: 45000, lines: 800 });

// Heartbeat
pulse.heartbeat();
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `AGENTPULSE_API_KEY` | API key (prefix: `ap_`) |
| `AGENTPULSE_ENDPOINT` | Custom API endpoint |
| `AGENTPULSE_AGENT` | Agent name (defaults to hostname) |

## How It Works

Events are queued in-memory and flushed every 10 seconds in batches. The flush timer is `unref()`'d so it won't keep your process alive. Events are fire-and-forget — failures are silently retried.

## License

MIT
