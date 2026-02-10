# AgentPulse — MVP Product Spec

> Lightweight monitoring for indie AI agents. Not enterprise bloat.

## Positioning

**Target:** Indie AI agent builders — solo devs running personal agents (OpenClaw, Claude Code, custom setups). NOT enterprises.

**Tagline:** "Your agent's vital signs."

**Why this exists:** Every LLM observability tool (Langfuse, Helicone, LangSmith, Braintrust) targets teams building LLM-powered apps. None of them care about *autonomous agents* — the always-on, cron-driven, memory-using agents that indie devs are building. We do.

---

## Competitor Landscape

| Tool | Free Tier | Paid | Core Focus | Gap |
|------|-----------|------|------------|-----|
| **Langfuse** | 50k units/mo | $29/mo (Core), $199/mo (Pro) | LLM tracing, evals, prompt mgmt | Open-source but complex; no agent-specific features |
| **Helicone** | 10k req/mo | $79/mo (Pro), $799/mo (Team) | API gateway + logging | Gateway-centric; overkill for single-agent setups |
| **LangSmith** | 5k traces/mo | $39/seat/mo (Plus) | LangChain ecosystem tracing | Locked to LangChain; expensive per-seat |
| **Braintrust** | 1M spans/mo | $249/mo (Pro) | Evals + observability | Enterprise-focused; $249 is absurd for a solo dev |
| **AgentOps.ai** | Free tier | Usage-based | Agent SDK monitoring | Closest competitor but SDK-heavy; targets frameworks |

**The gap:** All of these are *LLM API loggers* that bolt on agent features. None are purpose-built for the indie agent workflow: session monitoring, cron health, memory tracking, cost alerts, drift detection.

---

## Core Features (MVP)

### 1. 📡 Session Monitor
- Real-time view of active agent sessions
- Token usage per session, cost tracking
- Session timeline with key events
- Alert on stuck/long-running sessions

### 2. ⏰ Cron Health
- Dashboard of all scheduled jobs
- Success/failure rates, duration trends
- Alert on missed runs or consecutive failures
- Historical run log

### 3. 🧠 Memory Tracking
- Monitor memory file sizes over time
- Track daily log growth patterns
- Alert when memory approaches limits
- Visualize memory drift (topics, size, staleness)

### 4. 💰 Cost Alerts
- Real-time API cost tracking across providers
- Daily/weekly/monthly budgets with alerts
- Per-session cost breakdown
- Cost anomaly detection (sudden spikes)

### 5. 🔍 Drift Detection
- Track config changes over time
- Monitor agent behavior patterns
- Alert when outputs deviate from baselines
- System state snapshots (expected vs actual)

### 6. 📊 Dashboard
- Single-pane view of agent health
- Green/yellow/red status indicators
- Mobile-friendly (check your agent from your phone)
- Webhook integrations (Slack, Discord, iMessage)

### 7. 📜 Session Logging & Hierarchy
- Full session transcript logging (what the agent said/did)
- Visual session tree: main → sub-agents, cron spawns, DM sessions
- Click into any session to see full history
- Filter by status, duration, token usage
- "Replay" mode: step through a session's actions chronologically
- This is the killer feature competitors don't have — full visibility into autonomous agent behavior

### 8. 🤖 Agent-Readable Dashboard (API)
- Every dashboard view available as structured JSON via API
- Agents can query their own health: `pulse.status()` → returns current state
- Machine-readable alerts: agents can self-diagnose and self-heal
- MCP server integration: expose dashboard as MCP tools so any agent can read it
- Example: agent checks its own cost burn rate and throttles itself
- "Agents monitoring agents" — the meta play

---

## Architecture (MVP)

```
Agent (local) → AgentPulse SDK (lightweight) → AgentPulse API → Dashboard
                    │
                    └── Heartbeat pings, session events, cost data, cron results
```

**SDK:** Minimal Python/Node package. Few lines to integrate:
```python
from agentpulse import pulse

pulse.init(api_key="ap_...")
pulse.session_start("main")
pulse.cron_report("email-check", status="ok", duration_ms=1200)
pulse.cost_event(model="claude-opus-4", tokens=5000, cost=0.15)
pulse.heartbeat()
```

**Data model:**
- Events (sessions, cron runs, cost events, heartbeats)
- Alerts (configurable thresholds)
- Agents (one user can have multiple agents)

---

## Pricing

### Free (Hobby)
- 1 agent
- 10k events/month
- 7-day retention
- Basic dashboard
- Email alerts

### Pro — $15/month
- Unlimited agents
- 500k events/month
- 90-day retention
- Full dashboard + mobile
- Webhook alerts (Slack, Discord)
- Cost budgets & anomaly detection
- Drift detection
- Priority support

### Team — $49/month (future)
- Everything in Pro
- 5 team members
- Shared dashboards
- API access

---

## Payments & Billing

- **Stripe Checkout** for signup (hosted, we never touch card data)
- **Stripe Customer Portal** for manage/upgrade/downgrade/cancel
- **Stripe Webhooks** → CF Worker → update user tier in D1
- PCI compliance = Stripe's problem
- No card data ever hits our servers

### Tier Enforcement
- Event counter in D1, reset monthly. 429 when over limit.
- Agent count validated on ingest. Free rejects 2nd agent.
- R2 storage tracked per-user. Auto-prune oldest transcripts when over.
- Retention cron: purge events older than 7d (free) / 90d (pro).

### Unit Economics
| | Free | Pro ($15/mo) |
|---|---|---|
| D1 | ~$0 | ~$0.01 |
| R2 | ~$0 | ~$0.15 |
| Workers | ~$0 | ~$0.50 |
| Stripe | $0 | ~$0.73 |
| **Total cost** | **~$0** | **~$1.40** |
| **Margin** | — | **~90%** |

Break-even on Marcus's operating costs: ~3-4 Pro users.

---

## Tech Stack (MVP)

- **Backend:** Cloudflare Workers + D1 (structured data) + R2 (transcript blobs)
- **Frontend:** Static site (Astro or plain HTML) on Cloudflare Pages
- **Dashboard Auth:** Clerk (free 10K MAU, handles brute force/bot detection)
- **API Auth:** Scoped API keys — ingest (write-only) vs dashboard (read-only)
- **Email collection:** D1 table + Resend for transactional emails
- **SDK:** Python + Node packages on PyPI/npm
- **Hosting:** Cloudflare Pages (free)

## Security Architecture

### Rate Limiting
- Per-API-key: Free 100 req/min, Pro 1000 req/min
- Per-IP hard cap: 500 req/min regardless of key
- CF Workers built-in rate limiting

### Input Validation
- Max event payload: 10KB
- Max batch size: 100 events per request
- Strict JSON schema validation, reject malformed
- No raw SQL — D1 prepared statements only

### API Key Security
- 32+ byte random tokens, unguessable
- Hashed in DB (store hash, compare hash)
- Scoped: ingest keys (write-only) vs dashboard keys (read-only)
- Exposed SDK key can never read data

### Data Isolation
- Every query scoped to `agent_id` with row-level validation
- API key ownership verified on every request
- No cross-tenant data access possible

### DDoS / Abuse Prevention
- Cloudflare L3/L4 DDoS protection (automatic)
- L7: rate limiting + payload caps + required API key on all endpoints
- Clerk handles credential stuffing for dashboard login

### Encryption & Audit
- TLS everywhere (Cloudflare default)
- R2 encrypted at rest
- Audit log: API key CRUD, auth failures, rate limit hits

---

## Name: AgentPulse

**Domain:** agentpulse.dev (available on Porkbun, ~$11/yr)
**Alternatives:** agentpulse.io, agentpulse.app also appear available

**Why AgentPulse:**
- "Pulse" = vital signs, health monitoring — perfect metaphor
- Short, memorable, available
- Not confused with existing AgentOps.ai
- .dev TLD signals developer tool

---

## MVP Timeline

1. **Week 1:** Landing page + email collection, buy domain
2. **Week 2:** SDK (Python) + basic API (heartbeat, events)
3. **Week 3:** Dashboard (session view, cron health)
4. **Week 4:** Alerts (email, webhook), cost tracking
5. **Week 5:** Beta launch, dogfood with OpenClaw

---

## Success Metrics

- 100 email signups pre-launch
- 10 beta users running SDK
- <5 min integration time
- $0 infrastructure cost at MVP scale (Cloudflare free tier)
