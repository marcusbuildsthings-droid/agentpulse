/**
 * AgentPulse API — Cloudflare Worker + D1
 * Endpoints: POST /v1/ingest, GET /v1/events, GET /v1/stats, GET /v1/health
 */

interface Env {
  DB: D1Database;
  CORS_ORIGIN: string;
  RESEND_API_KEY?: string;
}

interface IngestPayload {
  agent: string;
  events: Array<{
    kind: string;
    ts: number;
    data: Record<string, unknown>;
    session?: string;
  }>;
}

const MAX_BODY_SIZE = 256 * 1024; // 256KB

// SHA-256 hash helper
async function sha256(input: string): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, "0")).join("");
}

// Simple API key validation (prefix: ap_)
function extractKey(req: Request): string | null {
  const auth = req.headers.get("Authorization") || "";
  if (auth.startsWith("Bearer ap_")) return auth.slice(7);
  return null;
}

// Rate limits per plan
const PLAN_LIMITS: Record<string, { eventsPerDay: number; maxBatchSize: number; retentionDays: number }> = {
  free: { eventsPerDay: 5000, maxBatchSize: 100, retentionDays: 7 },
  pro: { eventsPerDay: 100000, maxBatchSize: 500, retentionDays: 90 },
};

// In-memory register rate limit (by IP, resets on redeploy — good enough for spam prevention)
const registerAttempts = new Map<string, { count: number; resetAt: number }>();
const REGISTER_LIMIT = 5; // per hour per IP

function cors(req: Request, env: Env): Record<string, string> {
  const origin = req.headers.get("Origin") || "";
  const allowed = env.CORS_ORIGIN.split(",").map(s => s.trim());
  const matched = allowed.includes(origin) ? origin : "";
  return {
    "Access-Control-Allow-Origin": matched,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Vary": "Origin",
  };
}

function json(data: unknown, status = 200, req?: Request, env?: Env): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...(req && env ? cors(req, env) : {}) },
  });
}

// Check body size from Content-Length header
function checkBodySize(req: Request): boolean {
  const cl = parseInt(req.headers.get("Content-Length") || "0");
  return cl > MAX_BODY_SIZE;
}

// Read body with size enforcement
async function readBody<T>(req: Request): Promise<T | null> {
  const reader = req.body?.getReader();
  if (!reader) return null;
  const chunks: Uint8Array[] = [];
  let totalSize = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    totalSize += value.byteLength;
    if (totalSize > MAX_BODY_SIZE) return null;
    chunks.push(value);
  }
  const combined = new Uint8Array(totalSize);
  let offset = 0;
  for (const chunk of chunks) {
    combined.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return JSON.parse(new TextDecoder().decode(combined)) as T;
}

// Validate event kind: alphanumeric + underscore only
function isValidKind(kind: string): boolean {
  return typeof kind === "string" && /^[a-zA-Z0-9_]+$/.test(kind) && kind.length <= 64;
}

// Validate webhook URL: HTTPS only, no private IPs/metadata endpoints
function isValidWebhookUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") return false;
    const host = parsed.hostname.toLowerCase();
    if (host === "localhost" || host.endsWith(".local") || host === "[::1]") return false;
    if (/^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|127\.|0\.|169\.254\.)/.test(host)) return false;
    if (host === "169.254.169.254" || host === "metadata.google.internal") return false;
    return true;
  } catch {
    return false;
  }
}

// Validate timestamp: reasonable range (2020-01-01 to now + 1 day)
function isValidTs(ts: unknown): ts is number {
  if (typeof ts !== "number" || !Number.isFinite(ts)) return false;
  const min = 1577836800; // 2020-01-01
  const max = Date.now() / 1000 + 86400; // +1 day
  return ts >= min && ts <= max;
}

// ── Email Helper ──────────────────────────────────────
async function sendAlertEmail(
  env: Env, 
  to: string, 
  alertName: string, 
  metric: string, 
  value: number, 
  threshold: number, 
  agentName: string
): Promise<void> {
  if (!env.RESEND_API_KEY || !to) return;

  const subject = `🚨 AgentPulse Alert: ${alertName}`;
  const body = `
Your agent "${agentName}" has triggered an alert:

Alert: ${alertName}
Metric: ${metric}
Current Value: ${value}
Threshold: ${threshold}
Triggered At: ${new Date().toISOString()}

Check your AgentPulse dashboard for more details:
https://agentpulse-dashboard.pages.dev/

—
AgentPulse Monitoring
  `.trim();

  try {
    await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: "AgentPulse <alerts@marcusbuildsthings.dev>",
        to: [to],
        subject,
        text: body,
      }),
    });
  } catch (error) {
    // Silent fail - don't let email failures block the alert system
    console.error("Failed to send alert email:", error);
  }
}

// ── Alert Evaluation Engine ──────────────────────────────
// Fire-and-forget: runs after ingest, doesn't block response
function ctx_evaluateAlerts(env: Env, agentId: number, events: IngestPayload["events"]) {
  // Use waitUntil pattern — but since we don't have ctx here, we just fire async
  evaluateAlerts(env, agentId, events).catch(() => {});
}

async function evaluateAlerts(env: Env, agentId: number, events: IngestPayload["events"]) {
  const rules = await env.DB.prepare(
    "SELECT id, rule_name, condition, channel, webhook_url FROM alerts WHERE agent_id = ? AND enabled = 1"
  ).bind(agentId).all();

  if (!rules.results.length) return;

  for (const rule of rules.results) {
    const cond = JSON.parse(rule.condition as string) as { metric: string; op: string; threshold: number };
    let currentValue: number | null = null;

    switch (cond.metric) {
      case "daily_cost": {
        const row = await env.DB.prepare(
          "SELECT total_cost as val FROM cost_daily WHERE agent_id = ? AND date = date('now')"
        ).bind(agentId).first<{ val: number }>();
        currentValue = row?.val ?? 0;
        break;
      }
      case "daily_tokens": {
        const row = await env.DB.prepare(
          "SELECT total_tokens as val FROM cost_daily WHERE agent_id = ? AND date = date('now')"
        ).bind(agentId).first<{ val: number }>();
        currentValue = row?.val ?? 0;
        break;
      }
      case "daily_events": {
        const row = await env.DB.prepare(
          "SELECT COUNT(*) as val FROM events WHERE agent_id = ? AND ts >= ?"
        ).bind(agentId, Date.now() / 1000 - 86400).first<{ val: number }>();
        currentValue = row?.val ?? 0;
        break;
      }
      case "cron_fail_count": {
        const cronFails = events.filter(e => e.kind === "cron" && (e.data as any)?.status === "fail");
        if (cronFails.length === 0) continue; // Only evaluate when cron events come in
        const row = await env.DB.prepare(
          "SELECT COUNT(*) as val FROM events WHERE agent_id = ? AND kind = 'cron' AND json_extract(data, '$.status') = 'fail' AND ts >= ?"
        ).bind(agentId, Date.now() / 1000 - 86400).first<{ val: number }>();
        currentValue = row?.val ?? 0;
        break;
      }
      case "cron_fail_streak": {
        const cronEvents = events.filter(e => e.kind === "cron");
        if (cronEvents.length === 0) continue;
        // Check last N cron events for consecutive failures
        const recent = await env.DB.prepare(
          "SELECT json_extract(data, '$.status') as status FROM events WHERE agent_id = ? AND kind = 'cron' ORDER BY ts DESC LIMIT 10"
        ).bind(agentId).all();
        let streak = 0;
        for (const r of recent.results) {
          if ((r as any).status === "fail") streak++;
          else break;
        }
        currentValue = streak;
        break;
      }
    }

    if (currentValue === null) continue;

    let triggered = false;
    switch (cond.op) {
      case "gt": triggered = currentValue > cond.threshold; break;
      case "gte": triggered = currentValue >= cond.threshold; break;
      case "lt": triggered = currentValue < cond.threshold; break;
      case "lte": triggered = currentValue <= cond.threshold; break;
      case "eq": triggered = currentValue === cond.threshold; break;
    }

    if (!triggered) continue;

    // Deduplicate: don't fire same rule more than once per hour
    const recentFire = await env.DB.prepare(
      "SELECT id FROM events WHERE agent_id = ? AND kind = 'alert_fired' AND json_extract(data, '$.rule_id') = ? AND ts >= ?"
    ).bind(agentId, rule.id, Date.now() / 1000 - 3600).first();
    if (recentFire) continue;

    // Log the fired alert as an event
    const alertData = {
      rule_id: rule.id,
      rule_name: rule.rule_name,
      metric: cond.metric,
      value: currentValue,
      threshold: cond.threshold,
      op: cond.op,
    };
    await env.DB.prepare(
      "INSERT INTO events (agent_id, kind, ts, data) VALUES (?, 'alert_fired', ?, ?)"
    ).bind(agentId, Date.now() / 1000, JSON.stringify(alertData)).run();

    // Deliver alerts based on channel
    if (rule.channel === "webhook" && rule.webhook_url) {
      fetch(rule.webhook_url as string, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "agentpulse",
          alert: rule.rule_name,
          metric: cond.metric,
          value: currentValue,
          threshold: cond.threshold,
          fired_at: new Date().toISOString(),
        }),
      }).catch(() => {});
    } else if (rule.channel === "email") {
      // Get agent info for email delivery
      const agent = await env.DB.prepare(
        "SELECT name, email FROM agents WHERE id = ?"
      ).bind(agentId).first<{ name: string; email: string | null }>();
      
      if (agent?.email) {
        sendAlertEmail(
          env,
          agent.email,
          rule.rule_name as string,
          cond.metric,
          currentValue,
          cond.threshold,
          agent.name
        ).catch(() => {}); // Fire-and-forget, don't block
      }
    }
  }
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const path = url.pathname;

    // CORS preflight
    if (req.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors(req, env) });
    }

    // Health check (no auth)
    if (path === "/v1/health" && req.method === "GET") {
      return json({ status: "ok" }, 200, req, env);
    }

    // ── POST /v1/register (no auth, rate-limited) ──────────
    if (path === "/v1/register" && req.method === "POST") {
      // Body size check
      if (checkBodySize(req)) {
        return json({ error: "Request too large" }, 413, req, env);
      }

      // Rate limit by IP
      const ip = req.headers.get("CF-Connecting-IP") || "unknown";
      const now = Date.now();
      const attempt = registerAttempts.get(ip);
      if (attempt && attempt.resetAt > now && attempt.count >= REGISTER_LIMIT) {
        return json({ error: "Too many registrations. Try again later." }, 429, req, env);
      }
      if (!attempt || attempt.resetAt <= now) {
        registerAttempts.set(ip, { count: 1, resetAt: now + 3600_000 });
      } else {
        attempt.count++;
      }

      const body = await readBody<{ name: string; email?: string }>(req);
      if (!body) {
        return json({ error: "Invalid or oversized request body" }, 400, req, env);
      }
      if (!body.name || body.name.length < 2) {
        return json({ error: "Name required (min 2 chars)" }, 400, req, env);
      }
      if (body.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.email)) {
        return json({ error: "Invalid email format" }, 400, req, env);
      }

      // Generate key, store hash
      const raw = "ap_" + crypto.randomUUID().replace(/-/g, "");
      const keyHash = await sha256(raw);

      try {
        await env.DB.prepare(
          "INSERT INTO agents (name, api_key_hash, email, plan) VALUES (?, ?, ?, 'free')"
        ).bind(body.name, keyHash, body.email || null).run();
        return json({ name: body.name, api_key: raw, plan: "free" }, 201, req, env);
      } catch (e: any) {
        if (e.message?.includes("UNIQUE")) {
          return json({ error: "Name or email already registered" }, 409, req, env);
        }
        return json({ error: "Registration failed" }, 500, req, env);
      }
    }

    // ── POST /v1/heartbeat (authenticated) ────────────
    if (path === "/v1/heartbeat" && req.method === "POST") {
      const hbKey = extractKey(req);
      if (!hbKey) return json({ error: "Missing or invalid API key" }, 401, req, env);
      const hbHash = await sha256(hbKey);
      const hbAgent = await env.DB.prepare("SELECT id FROM agents WHERE api_key_hash = ?").bind(hbHash).first<{ id: number }>();
      if (!hbAgent) return json({ error: "Invalid API key" }, 403, req, env);
      await env.DB.prepare(
        "INSERT INTO heartbeats (agent_id, ts) VALUES (?, ?) ON CONFLICT(agent_id) DO UPDATE SET ts = excluded.ts"
      ).bind(hbAgent.id, new Date().toISOString()).run();
      return json({ ok: true }, 200, req, env);
    }

    // Auth required for everything else
    const apiKey = extractKey(req);
    if (!apiKey) {
      return json({ error: "Missing or invalid API key" }, 401, req, env);
    }

    // Look up agent by hashed API key
    const keyHash = await sha256(apiKey);
    const agent = await env.DB.prepare("SELECT id, name FROM agents WHERE api_key_hash = ?").bind(keyHash).first<{ id: number; name: string }>();
    if (!agent) {
      return json({ error: "Invalid API key" }, 403, req, env);
    }

    // ── POST /v1/ingest (rate-limited per plan) ────────────
    if (path === "/v1/ingest" && req.method === "POST") {
      // Body size check
      if (checkBodySize(req)) {
        return json({ error: "Request too large" }, 413, req, env);
      }

      const body = await readBody<IngestPayload>(req);
      if (!body) {
        return json({ error: "Invalid or oversized request body (max 256KB)" }, 413, req, env);
      }
      if (!body.events?.length) {
        return json({ error: "No events" }, 400, req, env);
      }

      // Hard cap: 500 events per batch regardless of plan
      if (body.events.length > 500) {
        return json({ error: "Max 500 events per batch" }, 413, req, env);
      }

      // Validate each event
      for (const e of body.events) {
        if (!isValidKind(e.kind)) {
          return json({ error: `Invalid event kind: must be alphanumeric/underscore, max 64 chars` }, 400, req, env);
        }
        if (!isValidTs(e.ts)) {
          return json({ error: "Invalid timestamp: must be a reasonable unix timestamp" }, 400, req, env);
        }
        if (e.data !== null && e.data !== undefined && typeof e.data !== "object") {
          return json({ error: "Event data must be an object" }, 400, req, env);
        }
        if (e.data && JSON.stringify(e.data).length > 16384) {
          return json({ error: "Event data too large (max 16KB)" }, 413, req, env);
        }
        if (e.session && (typeof e.session !== "string" || e.session.length > 256)) {
          return json({ error: "Session key too long (max 256 chars)" }, 400, req, env);
        }
      }

      // Look up plan limits
      const agentPlan = await env.DB.prepare("SELECT plan FROM agents WHERE id = ?").bind(agent.id).first<{ plan: string }>();
      const limits = PLAN_LIMITS[(agentPlan?.plan) || "free"] || PLAN_LIMITS.free;

      // Enforce batch size per plan
      if (body.events.length > limits.maxBatchSize) {
        return json({ error: `Batch too large. Max ${limits.maxBatchSize} events per request on ${agentPlan?.plan || "free"} plan.` }, 413, req, env);
      }

      // Check daily event count
      const todayCount = await env.DB.prepare(
        "SELECT COUNT(*) as cnt FROM events WHERE agent_id = ? AND ts >= ? "
      ).bind(agent.id, Date.now() / 1000 - 86400).first<{ cnt: number }>();

      if ((todayCount?.cnt || 0) + body.events.length > limits.eventsPerDay) {
        return json({ error: `Daily event limit reached (${limits.eventsPerDay} events/day on ${agentPlan?.plan || "free"} plan). Upgrade for higher limits.` }, 429, req, env);
      }

      const stmt = env.DB.prepare(
        "INSERT INTO events (agent_id, kind, ts, session_key, data) VALUES (?, ?, ?, ?, ?)"
      );

      const batch = body.events.slice(0, limits.maxBatchSize).map((e) =>
        stmt.bind(agent.id, e.kind, e.ts, e.session || null, JSON.stringify(e.data))
      );

      await env.DB.batch(batch);

      // Update cost aggregates if any cost events
      const costEvents = body.events.filter((e) => e.kind === "cost");
      if (costEvents.length > 0) {
        let totalCost = 0;
        let totalTokens = 0;
        for (const e of costEvents) {
          totalCost += (e.data.cost_usd as number) || 0;
          totalTokens += (e.data.tokens as number) || 0;
        }
        await env.DB.prepare(
          "INSERT INTO cost_daily (agent_id, date, total_cost, total_tokens, event_count) VALUES (?, date('now'), ?, ?, ?) ON CONFLICT(agent_id, date) DO UPDATE SET total_cost = total_cost + excluded.total_cost, total_tokens = total_tokens + excluded.total_tokens, event_count = event_count + excluded.event_count"
        ).bind(agent.id, totalCost, totalTokens, costEvents.length).run();
      }

      // ── Evaluate alert rules after ingest ──────────────────
      ctx_evaluateAlerts(env, agent.id, body.events);

      return json({ accepted: body.events.length }, 200, req, env);
    }

    // ── Alert Rules CRUD ────────────────────────────────────
    if (path === "/v1/alerts" && req.method === "GET") {
      const rows = await env.DB.prepare(
        "SELECT id, rule_name, condition, channel, webhook_url, enabled, created_at FROM alerts WHERE agent_id = ? ORDER BY created_at DESC"
      ).bind(agent.id).all();
      const alerts = rows.results.map((r: any) => ({ ...r, condition: JSON.parse(r.condition) }));
      return json({ alerts }, 200, req, env);
    }

    if (path === "/v1/alerts" && req.method === "POST") {
      if (checkBodySize(req)) return json({ error: "Request too large" }, 413, req, env);
      const body = await readBody<{
        rule_name: string;
        condition: { metric: string; op: string; threshold: number; window?: string };
        channel?: string;
        webhook_url?: string;
      }>(req);
      if (!body || !body.rule_name || !body.condition) {
        return json({ error: "rule_name and condition required" }, 400, req, env);
      }
      const { metric, op, threshold } = body.condition;
      if (!metric || !op || threshold === undefined) {
        return json({ error: "condition needs metric, op, threshold" }, 400, req, env);
      }
      const validOps = ["gt", "gte", "lt", "lte", "eq"];
      if (!validOps.includes(op)) {
        return json({ error: `op must be one of: ${validOps.join(", ")}` }, 400, req, env);
      }
      const validMetrics = ["daily_cost", "daily_tokens", "daily_events", "cron_fail_count", "cron_fail_streak"];
      if (!validMetrics.includes(metric)) {
        return json({ error: `metric must be one of: ${validMetrics.join(", ")}` }, 400, req, env);
      }
      const ch = body.channel || "webhook";
      if (ch === "webhook") {
        if (!body.webhook_url) {
          return json({ error: "webhook_url required for webhook channel" }, 400, req, env);
        }
        if (!isValidWebhookUrl(body.webhook_url)) {
          return json({ error: "Invalid webhook URL (must be HTTPS, no private IPs)" }, 400, req, env);
        }
      }
      // Limit: max 10 alert rules per agent on free plan
      const count = await env.DB.prepare("SELECT COUNT(*) as cnt FROM alerts WHERE agent_id = ?").bind(agent.id).first<{ cnt: number }>();
      if ((count?.cnt || 0) >= 10) {
        return json({ error: "Max 10 alert rules" }, 429, req, env);
      }
      const result = await env.DB.prepare(
        "INSERT INTO alerts (agent_id, rule_name, condition, channel, webhook_url) VALUES (?, ?, ?, ?, ?)"
      ).bind(agent.id, body.rule_name, JSON.stringify(body.condition), ch, body.webhook_url || null).run();
      return json({ id: result.meta.last_row_id, rule_name: body.rule_name, created: true }, 201, req, env);
    }

    // DELETE /v1/alerts/:id
    const alertDeleteMatch = path.match(/^\/v1\/alerts\/(\d+)$/);
    if (alertDeleteMatch && req.method === "DELETE") {
      const alertId = parseInt(alertDeleteMatch[1]);
      const deleted = await env.DB.prepare(
        "DELETE FROM alerts WHERE id = ? AND agent_id = ?"
      ).bind(alertId, agent.id).run();
      if (deleted.meta.changes === 0) return json({ error: "Not found" }, 404, req, env);
      return json({ deleted: true }, 200, req, env);
    }

    // PATCH /v1/alerts/:id (toggle enabled, update webhook, etc.)
    const alertPatchMatch = path.match(/^\/v1\/alerts\/(\d+)$/);
    if (alertPatchMatch && req.method === "PATCH") {
      if (checkBodySize(req)) return json({ error: "Request too large" }, 413, req, env);
      const alertId = parseInt(alertPatchMatch[1]);
      const body = await readBody<{ enabled?: boolean; webhook_url?: string; rule_name?: string }>(req);
      if (!body) return json({ error: "Invalid body" }, 400, req, env);
      const sets: string[] = [];
      const params: unknown[] = [];
      if (body.enabled !== undefined) { sets.push("enabled = ?"); params.push(body.enabled ? 1 : 0); }
      if (body.webhook_url !== undefined) {
        if (body.webhook_url && !isValidWebhookUrl(body.webhook_url)) {
          return json({ error: "Invalid webhook URL (must be HTTPS, no private IPs)" }, 400, req, env);
        }
        sets.push("webhook_url = ?"); params.push(body.webhook_url);
      }
      if (body.rule_name !== undefined) { sets.push("rule_name = ?"); params.push(body.rule_name); }
      if (sets.length === 0) return json({ error: "Nothing to update" }, 400, req, env);
      params.push(alertId, agent.id);
      await env.DB.prepare(`UPDATE alerts SET ${sets.join(", ")} WHERE id = ? AND agent_id = ?`).bind(...params).run();
      return json({ updated: true }, 200, req, env);
    }

    // GET /v1/alerts/history — fired alerts log
    if (path === "/v1/alerts/history" && req.method === "GET") {
      const limit = Math.min(parseInt(url.searchParams.get("limit") || "50"), 200);
      const rows = await env.DB.prepare(
        "SELECT ts, data FROM events WHERE agent_id = ? AND kind = 'alert_fired' ORDER BY ts DESC LIMIT ?"
      ).bind(agent.id, limit).all();
      const history = rows.results.map((r: any) => ({ ts: r.ts, ...JSON.parse(r.data) }));
      return json({ history }, 200, req, env);
    }

    // ── GET /v1/events ──────────────────────────────────────
    if (path === "/v1/events" && req.method === "GET") {
      const kind = url.searchParams.get("kind");
      const session = url.searchParams.get("session");
      const limit = Math.min(parseInt(url.searchParams.get("limit") || "100"), 1000);
      const since = url.searchParams.get("since"); // unix timestamp

      let sql = "SELECT id, kind, ts, session_key, data FROM events WHERE agent_id = ?";
      const params: unknown[] = [agent.id];

      if (kind) { sql += " AND kind = ?"; params.push(kind); }
      if (session) { sql += " AND session_key = ?"; params.push(session); }
      if (since) { sql += " AND ts >= ?"; params.push(parseFloat(since)); }

      sql += " ORDER BY ts DESC LIMIT ?";
      params.push(limit);

      const rows = await env.DB.prepare(sql).bind(...params).all();
      const events = rows.results.map((r: any) => ({
        ...r,
        data: JSON.parse(r.data as string),
      }));

      return json({ events, count: events.length }, 200, req, env);
    }

    // ── GET /v1/stats ───────────────────────────────────────
    if (path === "/v1/stats" && req.method === "GET") {
      const period = url.searchParams.get("period") || "24h";
      const sinceTs = period === "7d" ? Date.now() / 1000 - 604800
        : period === "30d" ? Date.now() / 1000 - 2592000
        : Date.now() / 1000 - 86400;
      const dateSince = period === "7d" ? "-7 days" : period === "30d" ? "-30 days" : "-1 day";

      const heartbeatRow = await env.DB.prepare(
        "SELECT ts FROM heartbeats WHERE agent_id = ?"
      ).bind(agent.id).first<{ ts: string }>();
      const lastSeen = heartbeatRow?.ts || null;
      const alive = lastSeen ? (Date.now() - new Date(lastSeen).getTime()) < 1200000 : false; // 20 minutes

      const [eventCounts, costData, cronHealth, topSessions, modelCosts, dailySpend, cronDetail] = await Promise.all([
        env.DB.prepare(
          "SELECT kind, COUNT(*) as count FROM events WHERE agent_id = ? AND ts >= ? GROUP BY kind"
        ).bind(agent.id, sinceTs).all(),

        env.DB.prepare(
          "SELECT SUM(total_cost) as cost, SUM(total_tokens) as tokens FROM cost_daily WHERE agent_id = ? AND date >= date('now', ?)"
        ).bind(agent.id, dateSince).first(),

        env.DB.prepare(
          "SELECT json_extract(data, '$.job') as job, json_extract(data, '$.status') as status, COUNT(*) as count FROM events WHERE agent_id = ? AND kind = 'cron' AND ts >= ? GROUP BY job, status"
        ).bind(agent.id, sinceTs).all(),

        // Top sessions by cost
        env.DB.prepare(
          "SELECT session_key as key, SUM(json_extract(data, '$.cost_usd')) as cost, SUM(COALESCE(json_extract(data, '$.tokens'),0)) as tokens, MAX(json_extract(data, '$.model')) as model, MAX(ts) - MIN(ts) as duration FROM events WHERE agent_id = ? AND kind = 'cost' AND session_key IS NOT NULL AND ts >= ? GROUP BY session_key ORDER BY cost DESC LIMIT 20"
        ).bind(agent.id, sinceTs).all(),

        // Model costs
        env.DB.prepare(
          "SELECT json_extract(data, '$.model') as model, SUM(json_extract(data, '$.cost_usd')) as cost, SUM(COALESCE(json_extract(data, '$.tokens'),0)) as tokens FROM events WHERE agent_id = ? AND kind = 'cost' AND json_extract(data, '$.model') IS NOT NULL AND ts >= ? GROUP BY model ORDER BY cost DESC"
        ).bind(agent.id, sinceTs).all(),

        // Daily spend from cost_daily
        env.DB.prepare(
          "SELECT date, total_cost as cost FROM cost_daily WHERE agent_id = ? AND date >= date('now', ?) ORDER BY date ASC"
        ).bind(agent.id, dateSince).all(),

        // Cron detail: last run per job
        env.DB.prepare(
          "SELECT json_extract(data, '$.job') as job, ts as last_run_ts, json_extract(data, '$.status') as last_status, json_extract(data, '$.duration_ms') as last_duration_ms, json_extract(data, '$.error') as last_error, json_extract(data, '$.summary') as last_summary FROM events WHERE agent_id = ? AND kind = 'cron' AND id IN (SELECT MAX(id) FROM events WHERE agent_id = ? AND kind = 'cron' GROUP BY json_extract(data, '$.job'))"
        ).bind(agent.id, agent.id).all(),
      ]);

      // Merge cron detail into cron_health
      const cronDetailMap: Record<string, any> = {};
      (cronDetail.results as any[]).forEach((r: any) => { cronDetailMap[r.job] = r; });
      const enrichedCronHealth = (cronHealth.results as any[]).map((r: any) => ({
        ...r,
        ...(cronDetailMap[r.job] ? {
          last_run_ts: cronDetailMap[r.job].last_run_ts,
          last_status: cronDetailMap[r.job].last_status,
          last_duration_ms: cronDetailMap[r.job].last_duration_ms,
          last_error: cronDetailMap[r.job].last_error,
          last_summary: cronDetailMap[r.job].last_summary,
        } : {}),
      }));

      return json({
        period,
        gateway_status: { last_seen: lastSeen, alive },
        events: Object.fromEntries(eventCounts.results.map((r: any) => [r.kind, r.count])),
        cost: { usd: (costData as any)?.cost || 0, tokens: (costData as any)?.tokens || 0 },
        cron_health: enrichedCronHealth,
        top_sessions: (topSessions.results as any[]).map((r: any) => ({ key: r.key, cost: r.cost || 0, tokens: r.tokens || 0, model: r.model || '', duration: r.duration || 0 })),
        model_costs: (modelCosts.results as any[]).map((r: any) => ({ model: r.model || 'unknown', cost: r.cost || 0, tokens: r.tokens || 0 })),
        daily_spend: (dailySpend.results as any[]).map((r: any) => ({ date: r.date, cost: r.cost || 0 })),
      }, 200, req, env);
    }

    // ── GET /v1/sessions ─────────────────────────────────────
    if (path === "/v1/sessions" && req.method === "GET") {
      const since = url.searchParams.get("since") || String(Date.now() / 1000 - 86400);
      const [rows, costRows, jobRows] = await Promise.all([
        env.DB.prepare(
          "SELECT session_key, MIN(ts) as started, MAX(ts) as last_active, COUNT(*) as events " +
          "FROM events WHERE agent_id = ? AND session_key IS NOT NULL AND ts >= ? " +
          "GROUP BY session_key ORDER BY last_active DESC"
        ).bind(agent.id, parseFloat(since)).all(),
        env.DB.prepare(
          "SELECT session_key, SUM(json_extract(data, '$.cost_usd')) as cost, SUM(COALESCE(json_extract(data, '$.tokens'),0)) as tokens, MAX(json_extract(data, '$.model')) as model " +
          "FROM events WHERE agent_id = ? AND kind = 'cost' AND session_key IS NOT NULL AND ts >= ? " +
          "GROUP BY session_key"
        ).bind(agent.id, parseFloat(since)).all(),
        // Get job names and labels from session events (reporter includes job_name/label in session data)
        env.DB.prepare(
          "SELECT session_key, json_extract(data, '$.job_name') as job_name, json_extract(data, '$.label') as label, MAX(json_extract(data, '$.type')) as session_type " +
          "FROM events WHERE agent_id = ? AND kind = 'session' AND session_key IS NOT NULL AND ts >= ? AND (json_extract(data, '$.job_name') IS NOT NULL OR json_extract(data, '$.label') IS NOT NULL) " +
          "GROUP BY session_key"
        ).bind(agent.id, parseFloat(since)).all(),
      ]);
      const costMap: Record<string, any> = {};
      (costRows.results as any[]).forEach((r: any) => { costMap[r.session_key] = { cost: r.cost || 0, tokens: r.tokens || 0, model: r.model || '' }; });
      const jobMap: Record<string, any> = {};
      (jobRows.results as any[]).forEach((r: any) => { jobMap[r.session_key] = { job_name: r.job_name, label: r.label, session_type: r.session_type }; });

      // Helper: resolve job_name for cron sessions by checking parent UUID
      function resolveJobName(key: string): string | null {
        if (jobMap[key]?.job_name) return jobMap[key].job_name;
        // For :run: sub-sessions, try the parent cron key
        const runIdx = key.indexOf(':run:');
        if (runIdx > 0) {
          const parentKey = key.substring(0, runIdx);
          if (jobMap[parentKey]?.job_name) return jobMap[parentKey].job_name;
        }
        // Try matching any jobMap entry that shares the same cron UUID
        const cronMatch = key.match(/:cron:([0-9a-f-]+)/);
        if (cronMatch) {
          const uuid = cronMatch[1];
          for (const [k, v] of Object.entries(jobMap)) {
            if (k.includes(uuid) && v.job_name) return v.job_name;
          }
        }
        return null;
      }

      const sessions = (rows.results as any[]).map((r: any) => ({
        ...r,
        cost: costMap[r.session_key]?.cost || 0,
        tokens: costMap[r.session_key]?.tokens || 0,
        model: costMap[r.session_key]?.model || '',
        job_name: resolveJobName(r.session_key),
        label: jobMap[r.session_key]?.label || null,
        session_type: jobMap[r.session_key]?.session_type || null,
      }));
      return json({ sessions }, 200, req, env);
    }

    // ── GET /v1/mailbox ──────────────────────────────────────
    if (path === "/v1/mailbox" && req.method === "GET") {
      const since = url.searchParams.get("since") || String(Date.now() / 1000 - 86400);
      const limit = Math.min(parseInt(url.searchParams.get("limit") || "200"), 1000);
      const rows = await env.DB.prepare(
        "SELECT ts, " +
        "json_extract(data, '$.from') as sender, " +
        "json_extract(data, '$.to') as receiver, " +
        "json_extract(data, '$.type') as msg_type, " +
        "json_extract(data, '$.summary') as summary, " +
        "json_extract(data, '$.team') as team " +
        "FROM events WHERE agent_id = ? AND kind = 'mailbox' AND ts >= ? " +
        "ORDER BY ts DESC LIMIT ?"
      ).bind(agent.id, parseFloat(since), limit).all();
      return json({ messages: rows.results, count: rows.results.length }, 200, req, env);
    }

    // ── GET /v1/crons ───────────────────────────────────────
    if (path === "/v1/crons" && req.method === "GET") {
      const rows = await env.DB.prepare(
        "SELECT json_extract(data, '$.job') as job, kind, ts, " +
        "json_extract(data, '$.status') as status, " +
        "json_extract(data, '$.duration_ms') as duration_ms " +
        "FROM events WHERE agent_id = ? AND kind = 'cron' " +
        "ORDER BY ts DESC LIMIT 50"
      ).bind(agent.id).all();
      return json({ crons: rows.results }, 200, req, env);
    }

    // ── DELETE /v1/cleanup (clean up null cron jobs) ────
    if (path === "/v1/cleanup" && req.method === "DELETE") {
      const result = await env.DB.prepare(
        "DELETE FROM events WHERE agent_id = ? AND kind = 'cron' AND (json_extract(data, '$.job') IS NULL OR json_extract(data, '$.job') = 'null')"
      ).bind(agent.id).run();
      return json({ deleted: result.meta.changes }, 200, req, env);
    }

    return json({ error: "Not found" }, 404, req, env);
  },

  // Scheduled: retention cleanup (run daily via CF cron trigger)
  async scheduled(_event: ScheduledEvent, env: Env, _ctx: ExecutionContext): Promise<void> {
    // Delete events past retention for each plan
    for (const [plan, limits] of Object.entries(PLAN_LIMITS)) {
      const cutoff = Date.now() / 1000 - limits.retentionDays * 86400;
      await env.DB.prepare(
        "DELETE FROM events WHERE agent_id IN (SELECT id FROM agents WHERE plan = ?) AND ts < ?"
      ).bind(plan, cutoff).run();
    }
    // Also clean up cost_daily older than 90 days for everyone
    await env.DB.prepare("DELETE FROM cost_daily WHERE date < date('now', '-90 days')").run();
  },
};
