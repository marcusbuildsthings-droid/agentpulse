# AgentPulse

Lightweight monitoring for indie AI agents. Your agent's vital signs.

## Status

**Stage:** Pre-launch MVP build

### What's Built
- [x] Product spec (SPEC.md)
- [x] Landing page (landing/index.html)
- [x] Python SDK v0.1.0 (sdk-python/) — zero dependencies, fire-and-forget batching
- [x] API backend (api/) — Cloudflare Workers + D1 (SQLite)
- [x] Database schema (api/schema.sql) — events, cost aggregation, alerts
- [x] Dashboard frontend (dashboard/) — static SPA, dark theme, demo mode
- [x] Node.js SDK (sdk-node/) — zero dependencies, TypeScript, fire-and-forget
- [x] Local dev server (api/dev-server.py) — same API, local SQLite, zero deps
- [x] OpenClaw dogfood reporter (dogfood/openclaw-reporter.py) — pipes marcus-* data into AgentPulse
- [ ] Domain (agentpulse.dev)
- [ ] Deploy API to Cloudflare
- [x] Publish SDK to PyPI (`pip install agentpulse-sdk`)
- [ ] Dashboard → live API (currently demo mode only)

### Architecture
```
Agent → SDK (Python/Node) → API (CF Workers) → D1 (SQLite) → Dashboard
```

### Progress Log
- **2026-02-06:** Spec, landing page, repo init
- **2026-02-06:** Python SDK (client.py — batched event queue, 9 event types), API worker (ingest, events, stats endpoints), D1 schema
- **2026-02-08:** Node.js SDK — full TypeScript, zero deps, same API surface as Python SDK. Compiles and tests clean.
- **2026-02-07:** Dashboard frontend — full SPA with overview, sessions, costs, cron health, event stream views. Demo mode (?demo), 30s auto-refresh, dark theme, responsive. All core MVP views complete.
- **2026-02-09:** Local dev server (api/dev-server.py) — full API parity with CF Worker, SQLite backend, auto-creates agent on first run. Tested: 11 real events ingested from OpenClaw.
- **2026-02-09:** OpenClaw dogfood reporter
- **2026-02-10:** Python SDK published to PyPI as `agentpulse-sdk`. GitHub repo pushed (clean, no node_modules). PyPI name `agentpulse` was taken, using `agentpulse-sdk` instead. (dogfood/openclaw-reporter.py) — collects sessions, costs, crons, memory health from marcus-* tools and reports to AgentPulse API. Verified working end-to-end.

## Structure
```
agentops/
├── SPEC.md           # Product spec
├── landing/          # Landing page
├── dashboard/        # Dashboard SPA (open ?demo for preview)
├── docs/             # Documentation site
├── sdk-python/       # Python SDK (agentpulse)
│   └── agentpulse/
│       ├── __init__.py
│       └── client.py
├── sdk-node/         # Node.js SDK (agentpulse)
│   └── src/
│       └── index.ts
├── dogfood/          # Dogfooding tools
│   └── openclaw-reporter.py  # marcus-* → AgentPulse
└── api/              # Cloudflare Workers API
    ├── src/index.ts
    ├── dev-server.py   # Local dev server (SQLite)
    ├── schema.sql
    └── wrangler.toml
```

## SDK Quick Start
```python
from agentpulse import init, pulse

init(api_key="ap_...")
pulse.session_start("main")
pulse.cost_event(model="claude-opus-4", input_tokens=5000, cost=0.15)
pulse.cron_report("backup", status="ok", duration_ms=3400)
pulse.heartbeat()
```

## License
MIT
