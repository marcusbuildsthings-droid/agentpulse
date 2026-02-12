# Mailbox Visualization — TODO

## API ✅ Done
- `GET /v1/mailbox?since=&limit=` endpoint deployed
- Accepts `mailbox` events via standard `/v1/ingest` with kind=mailbox
- Data shape: `{from, to, type, summary, team}`

## Ingestion — Next
- Option A: Patch `agent-teams` Python CLI to emit AgentPulse events natively (cleanest)
- Option B: Use `/Users/ape/clawd/scripts/agent-teams-hook.sh` wrapper
- Option C: Periodic scan of `~/.agent-teams/` mailbox files and batch-ingest
- **Recommended: Option A** — add `--telemetry-url` and `--telemetry-key` flags or env vars to agent-teams

## Dashboard — After ingestion works
- Message flow graph: nodes = agents, edges = messages (thickness = volume)
- Timeline view: chronological stream of inter-agent messages
- Filter by team, time range, message type
- Click a message to see full summary
- Highlight active conversations vs idle agents

## Env vars needed
- AGENTPULSE_API_URL=https://agentpulse-api.marcus-builds-things.workers.dev
- AGENTPULSE_API_KEY=ap_7062b8308d8b423baef5a293c3eb8bfd
