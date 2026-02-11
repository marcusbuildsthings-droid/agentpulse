# Deploying AgentPulse API

## Cloudflare Workers (recommended)

### Prerequisites
- Cloudflare account
- `wrangler` CLI (`npm install -g wrangler`)
- Authenticated: `wrangler login`

### Steps

1. **Create D1 database:**
   ```bash
   cd api/
   wrangler d1 create agentpulse
   ```
   Copy the `database_id` from the output into `wrangler.toml`.

2. **Initialize schema:**
   ```bash
   npm run db:init
   ```

3. **Deploy:**
   ```bash
   npm run deploy
   ```

4. **Register your first agent:**
   ```bash
   curl -X POST https://agentpulse-api.<your-subdomain>.workers.dev/v1/register \
     -H "Content-Type: application/json" \
     -d '{"name": "my-agent", "email": "you@example.com"}'
   ```
   Save the returned `api_key`.

5. **Connect dashboard:**
   Open `dashboard/index.html`, go to Settings, paste the Worker URL and API key.

## Local Development

```bash
cd api/
python3 dev-server.py --port 8787
```

The dev server auto-creates a `marcus` agent and prints its API key.

## Self-hosting (Docker/VPS)

The dev server (`dev-server.py`) is a zero-dependency Python server suitable for self-hosting:

```bash
python3 dev-server.py --port 8787 --db /data/agentpulse.db
```

Put behind nginx/caddy for TLS. That's it.
