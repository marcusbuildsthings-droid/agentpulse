# AgentPulse Security Audit

**Date:** 2026-02-12  
**Auditor:** Automated security review  
**Scope:** API (Cloudflare Worker), Dashboard SPA, Python SDK, Node SDK, Database schema  

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 2 |
| High | 4 |
| Medium | 4 |
| Low | 3 |
| Info | 2 |

---

## Critical Findings

### C1. API Keys Stored in Plaintext in Database

**File:** `api/schema.sql`, `api/src/index.ts`  
**Severity:** Critical  

API keys are stored as plaintext in the `agents` table and looked up via direct comparison (`WHERE api_key = ?`). If the D1 database is ever leaked, exported, or accessed by an insider, all API keys are immediately compromised.

**Additionally**, the `/v1/register` endpoint returns the raw API key in the response body. This is the only time the user sees it, which is fine — but it must be the *only* copy of the plaintext.

**Fix:** Store a SHA-256 hash of the key. Return the plaintext only once at registration.

```typescript
// At registration:
const raw = "ap_" + crypto.randomUUID().replace(/-/g, "");
const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw));
const keyHash = [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, "0")).join("");

await env.DB.prepare(
  "INSERT INTO agents (name, api_key_hash, email, plan) VALUES (?, ?, ?, 'free')"
).bind(body.name, keyHash, body.email || null).run();

// Return raw key to user (only time it's shown)
return json({ name: body.name, api_key: raw, plan: "free" }, 201, env);

// At auth time:
async function lookupAgent(apiKey: string, env: Env) {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(apiKey));
  const keyHash = [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, "0")).join("");
  return env.DB.prepare("SELECT id, name FROM agents WHERE api_key_hash = ?").bind(keyHash).first();
}
```

---

### C2. CORS Origin Set to Wildcard (`*`)

**File:** `api/src/index.ts` (env variable `CORS_ORIGIN`), configuration  
**Severity:** Critical  

The CORS origin defaults to `*` (per task description). This means any website can make authenticated requests to the API using a victim's browser-stored credentials or trick users into making requests from malicious pages.

Combined with the dashboard storing the API key in `localStorage` and making `fetch()` calls with `Authorization` headers, an attacker's site can't directly steal the key (since it's in a different origin's localStorage). However, the wildcard CORS allows any origin to call the API if they have a key, meaning there's zero origin restriction.

**Fix:** Set `CORS_ORIGIN` to the specific dashboard domain(s):

```toml
# wrangler.toml
[vars]
CORS_ORIGIN = "https://dashboard.agentpulse.dev"
```

If multiple origins are needed, implement dynamic checking:

```typescript
function cors(req: Request, env: Env): Record<string, string> {
  const origin = req.headers.get("Origin") || "";
  const allowed = ["https://dashboard.agentpulse.dev", "https://agentpulse.dev"];
  const matchedOrigin = allowed.includes(origin) ? origin : "";
  return {
    "Access-Control-Allow-Origin": matchedOrigin,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Vary": "Origin",
  };
}
```

---

## High Findings

### H1. XSS via Event Data in Dashboard

**File:** `dashboard/index.html`  
**Severity:** High  

Multiple locations inject untrusted data using string interpolation into `innerHTML`:

1. **Event stream** — `e.kind`, `e.session_key`, and `JSON.stringify(e.data)` are injected directly:
   ```javascript
   `<span class="kind">${e.kind}</span>`
   `<span class="detail">${detail}</span>`
   ```

2. **Event breakdown table** — `k` (event kind from API) is injected:
   ```javascript
   `<tr><td>${k}</td><td>${v}</td></tr>`
   ```

3. **Sessions table** — `e.session_key`, `e.data?.model`, `e.data?.channel` injected unescaped.

4. **Cron table** — `name` (job name) injected unescaped.

An attacker who can inject events (anyone with an API key, or through a compromised agent) can store XSS payloads as event kinds, session keys, or data fields like `<img src=x onerror=alert(document.cookie)>`.

**Fix:** Add an escape function and use it everywhere:

```javascript
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// Then:
`<span class="kind">${esc(e.kind)}</span>`
`<span class="detail">${esc(detail)}</span>`
`<tr><td>${esc(k)}</td><td>${v}</td></tr>`
```

Better yet, use `textContent` or DOM APIs instead of `innerHTML` with string templates.

---

### H2. No Input Validation on Event Data (API)

**File:** `api/src/index.ts` — `/v1/ingest`  
**Severity:** High  

The ingest endpoint accepts arbitrary event data with no validation:

- `kind` — no whitelist; any string accepted
- `ts` — no range check; can be negative, zero, or far future (breaks queries)
- `data` — arbitrary JSON with no size limit per-event; `JSON.stringify(e.data)` could be megabytes
- `session` — no length/format validation

An attacker could:
- Inject absurdly large `data` blobs to bloat the D1 database
- Use future timestamps to evade retention cleanup
- Stuff arbitrary HTML/JS in fields (feeds into XSS in H1)

**Fix:**

```typescript
// Validate each event
const VALID_KINDS = new Set(["session", "cron", "cost", "heartbeat", "metric", "memory", "alert", "mailbox"]);
const MAX_DATA_SIZE = 4096;

for (const e of body.events) {
  if (!VALID_KINDS.has(e.kind)) return json({ error: `Invalid event kind: ${e.kind}` }, 400, env);
  if (typeof e.ts !== "number" || e.ts < 1600000000 || e.ts > Date.now()/1000 + 86400) {
    return json({ error: "Invalid timestamp" }, 400, env);
  }
  const dataStr = JSON.stringify(e.data);
  if (dataStr.length > MAX_DATA_SIZE) return json({ error: "Event data too large" }, 400, env);
  if (e.session && e.session.length > 256) return json({ error: "Session key too long" }, 400, env);
}
```

---

### H3. API Key Stored in localStorage (Dashboard)

**File:** `dashboard/index.html`  
**Severity:** High  

The dashboard stores the API key in `localStorage`:
```javascript
localStorage.setItem('ap_api_key', state.apiKey);
```

`localStorage` is accessible to any JavaScript running on the same origin, making it vulnerable to XSS (see H1). If XSS is achieved, the attacker gets the API key.

**Fix:** Use `sessionStorage` (cleared on tab close) at minimum. Ideally, use a proper auth flow with `httpOnly` cookies, or prompt for the key each session without persisting it.

```javascript
// Minimum improvement: sessionStorage
sessionStorage.setItem('ap_api_key', state.apiKey);

// Better: don't persist at all, prompt on load
```

---

### H4. No Request Body Size Limit

**File:** `api/src/index.ts`  
**Severity:** High  

`await req.json()` is called without checking `Content-Length`. An attacker could send a multi-GB JSON body to exhaust Worker memory/CPU.

**Fix:**

```typescript
const contentLength = parseInt(req.headers.get("Content-Length") || "0");
if (contentLength > 1_000_000) { // 1MB max
  return json({ error: "Request too large" }, 413, env);
}
const body = await req.json();
```

---

## Medium Findings

### M1. Registration Rate Limiting is In-Memory Only

**File:** `api/src/index.ts`  
**Severity:** Medium  

```javascript
const registerAttempts = new Map<string, { count: number; resetAt: number }>();
```

This map lives in Worker memory and resets on every deploy or isolate recycle (which happens frequently on Cloudflare Workers — isolates are ephemeral). An attacker can spam registrations by simply waiting for isolate recycling, or targeting different edge locations.

**Fix:** Use D1 or Cloudflare KV/Durable Objects for rate limiting:

```typescript
// Using D1 (simple approach):
const recent = await env.DB.prepare(
  "SELECT COUNT(*) as cnt FROM agents WHERE created_at > datetime('now', '-1 hour')"
).first<{ cnt: number }>();
if ((recent?.cnt || 0) > 100) {
  return json({ error: "Registration rate limit exceeded" }, 429, env);
}
```

---

### M2. No Rate Limiting on Authenticated Endpoints (Beyond Daily Count)

**File:** `api/src/index.ts`  
**Severity:** Medium  

While `/v1/ingest` has daily event count limits, there's no per-second/per-minute rate limiting on any endpoint. An attacker with a valid key could:
- Hammer `/v1/events`, `/v1/stats`, `/v1/sessions` etc. to cause D1 read pressure
- Run expensive aggregation queries (`/v1/stats`) in rapid succession

**Fix:** Add per-minute rate limiting per API key, ideally via Cloudflare Rate Limiting rules, or a simple in-D1 counter.

---

### M3. No `email` Column Validation

**File:** `api/src/index.ts` — `/v1/register`  
**Severity:** Medium  

The `email` field is stored without any format validation. Since `email` has a `UNIQUE` constraint, an attacker could register with arbitrary strings as "emails" to block real users from registering.

```javascript
// No validation:
body.email || null
```

**Fix:**

```typescript
if (body.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.email)) {
  return json({ error: "Invalid email format" }, 400, env);
}
```

---

### M4. `name` Field — SQL Injection Safe but No Sanitization

**File:** `api/src/index.ts`  
**Severity:** Medium  

The D1 parameterized queries prevent SQL injection (good!). However, `name` has no length limit, character restrictions, or uniqueness enforcement beyond the DB constraint. Names could contain HTML/JS that ends up displayed somewhere.

**Fix:** Add length and character validation:

```typescript
if (body.name.length > 64 || !/^[\w\s.-]+$/.test(body.name)) {
  return json({ error: "Invalid name (alphanumeric, max 64 chars)" }, 400, env);
}
```

---

## Low Findings

### L1. API Key Entropy Could Be Stronger

**File:** `api/src/index.ts`  
**Severity:** Low  

```javascript
const key = "ap_" + crypto.randomUUID().replace(/-/g, "");
```

`crypto.randomUUID()` gives 122 bits of entropy (UUIDv4), which is adequate. However, the `ap_` prefix + 32 hex chars = 35 char key. Consider using `crypto.getRandomValues()` with base62 encoding for higher density:

```typescript
const buf = new Uint8Array(32);
crypto.getRandomValues(buf);
const key = "ap_" + [...buf].map(b => b.toString(36).padStart(2, "0")).join("").slice(0, 40);
```

This is a minor improvement; current entropy is acceptable.

---

### L2. No HTTPS Enforcement in SDKs

**File:** `sdk-python/agentpulse/client.py`, `sdk-node/dist/index.js`  
**Severity:** Low  

Both SDKs allow arbitrary endpoints including `http://`:

```python
self.endpoint = (endpoint or os.environ.get("AGENTPULSE_ENDPOINT", _DEFAULT_ENDPOINT)).rstrip("/")
```

API keys would be sent in plaintext over HTTP.

**Fix:**

```python
if not self.endpoint.startswith("https://") and "localhost" not in self.endpoint:
    raise ValueError("AgentPulse endpoint must use HTTPS")
```

---

### L3. Version/Debug Information Disclosure

**File:** `api/src/index.ts`  
**Severity:** Low  

The `/v1/health` endpoint returns the version with no auth:
```json
{"status": "ok", "version": "0.1.0"}
```

Minor information disclosure. Consider removing version from unauthenticated responses in production.

---

## Info Findings

### I1. No Plan Upgrade/Downgrade Endpoint

**Severity:** Info  

The `plan` column in `agents` can only be set to `'free'` at registration. There's no endpoint to change plans, meaning it must be done via direct DB access. Not a vulnerability, but a gap.

---

### I2. Alerts Table Unused

**Severity:** Info  

The `alerts` table exists in schema but no API endpoints reference it. The `webhook_url` field in particular could become an SSRF vector if an alert-sending feature is added without validation.

**Future-proofing fix:** When implementing alerts, validate `webhook_url` against an allowlist of schemes (`https://` only) and block private IPs.

---

## Positive Findings

- ✅ **D1 parameterized queries** — No SQL injection vulnerabilities found
- ✅ **Agent-scoped data access** — All authenticated queries filter by `agent_id` from the API key lookup, preventing IDOR
- ✅ **Daemon threads in Python SDK** — Worker thread is daemonic, won't prevent process exit
- ✅ **`timer.unref()` in Node SDK** — Won't keep Node process alive
- ✅ **Batch processing** — Events are batched efficiently
- ✅ **No hardcoded secrets** — No API keys, tokens, or credentials found in source code
- ✅ **Retention cleanup** — Scheduled worker handles data lifecycle

---

## Priority Remediation Order

1. **C1** — Hash API keys in database (breaking change, requires migration)
2. **H1** — Fix XSS in dashboard (quick win, add `esc()` helper)
3. **C2** — Restrict CORS origin (config change)
4. **H2** — Add input validation on ingest (code change)
5. **H4** — Add request body size limit
6. **H3** — Stop persisting API key in localStorage
7. **M1–M4** — Rate limiting and input validation improvements
