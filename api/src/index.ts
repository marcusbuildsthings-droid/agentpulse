/**
 * AgentPulse API — Cloudflare Worker + D1
 * Endpoints: POST /v1/ingest, GET /v1/events, GET /v1/stats, GET /v1/health
 */

interface Env {
  DB: D1Database;
  CORS_ORIGIN: string;
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

function cors(env: Env): Record<string, string> {
  return {
    "Access-Control-Allow-Origin": env.CORS_ORIGIN,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
  };
}

function json(data: unknown, status = 200, env?: Env): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...(env ? cors(env) : {}) },
  });
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const path = url.pathname;

    // CORS preflight
    if (req.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors(env) });
    }

    // Health check (no auth)
    if (path === "/v1/health" && req.method === "GET") {
      return json({ status: "ok", version: "0.1.0" }, 200, env);
    }

    // ── POST /v1/register (no auth, rate-limited) ──────────
    if (path === "/v1/register" && req.method === "POST") {
      // Rate limit by IP
      const ip = req.headers.get("CF-Connecting-IP") || "unknown";
      const now = Date.now();
      const attempt = registerAttempts.get(ip);
      if (attempt && attempt.resetAt > now && attempt.count >= REGISTER_LIMIT) {
        return json({ error: "Too many registrations. Try again later." }, 429, env);
      }
      if (!attempt || attempt.resetAt <= now) {
        registerAttempts.set(ip, { count: 1, resetAt: now + 3600_000 });
      } else {
        attempt.count++;
      }

      const body = (await req.json()) as { name: string; email?: string };
      if (!body.name || body.name.length < 2) {
        return json({ error: "Name required (min 2 chars)" }, 400, env);
      }
      const key = "ap_" + crypto.randomUUID().replace(/-/g, "");
      try {
        await env.DB.prepare(
          "INSERT INTO agents (name, api_key, email, plan) VALUES (?, ?, ?, 'free')"
        ).bind(body.name, key, body.email || null).run();
        return json({ name: body.name, api_key: key, plan: "free" }, 201, env);
      } catch (e: any) {
        if (e.message?.includes("UNIQUE")) {
          return json({ error: "Name or email already registered" }, 409, env);
        }
        return json({ error: "Registration failed" }, 500, env);
      }
    }

    // Auth required for everything else
    const apiKey = extractKey(req);
    if (!apiKey) {
      return json({ error: "Missing or invalid API key" }, 401, env);
    }

    // Look up agent by API key
    const agent = await env.DB.prepare("SELECT id, name FROM agents WHERE api_key = ?").bind(apiKey).first<{ id: number; name: string }>();
    if (!agent) {
      return json({ error: "Invalid API key" }, 403, env);
    }

    // ── POST /v1/ingest (rate-limited per plan) ────────────
    if (path === "/v1/ingest" && req.method === "POST") {
      const body = (await req.json()) as IngestPayload;
      if (!body.events?.length) {
        return json({ error: "No events" }, 400, env);
      }

      // Look up plan limits
      const agentPlan = await env.DB.prepare("SELECT plan FROM agents WHERE id = ?").bind(agent.id).first<{ plan: string }>();
      const limits = PLAN_LIMITS[(agentPlan?.plan) || "free"] || PLAN_LIMITS.free;

      // Enforce batch size
      if (body.events.length > limits.maxBatchSize) {
        return json({ error: `Batch too large. Max ${limits.maxBatchSize} events per request on ${agentPlan?.plan || "free"} plan.` }, 413, env);
      }

      // Check daily event count
      const todayCount = await env.DB.prepare(
        "SELECT COUNT(*) as cnt FROM events WHERE agent_id = ? AND ts >= ? "
      ).bind(agent.id, Date.now() / 1000 - 86400).first<{ cnt: number }>();

      if ((todayCount?.cnt || 0) + body.events.length > limits.eventsPerDay) {
        return json({ error: `Daily event limit reached (${limits.eventsPerDay} events/day on ${agentPlan?.plan || "free"} plan). Upgrade for higher limits.` }, 429, env);
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
          totalTokens += ((e.data.input_tokens as number) || 0) + ((e.data.output_tokens as number) || 0);
        }
        await env.DB.prepare(
          "INSERT INTO cost_daily (agent_id, date, total_cost, total_tokens, event_count) VALUES (?, date('now'), ?, ?, ?) ON CONFLICT(agent_id, date) DO UPDATE SET total_cost = total_cost + excluded.total_cost, total_tokens = total_tokens + excluded.total_tokens, event_count = event_count + excluded.event_count"
        ).bind(agent.id, totalCost, totalTokens, costEvents.length).run();
      }

      return json({ accepted: body.events.length }, 200, env);
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

      return json({ events, count: events.length }, 200, env);
    }

    // ── GET /v1/stats ───────────────────────────────────────
    if (path === "/v1/stats" && req.method === "GET") {
      const period = url.searchParams.get("period") || "24h";
      const sinceTs = period === "7d" ? Date.now() / 1000 - 604800
        : period === "30d" ? Date.now() / 1000 - 2592000
        : Date.now() / 1000 - 86400;

      const [eventCounts, costData, cronHealth] = await Promise.all([
        env.DB.prepare(
          "SELECT kind, COUNT(*) as count FROM events WHERE agent_id = ? AND ts >= ? GROUP BY kind"
        ).bind(agent.id, sinceTs).all(),

        env.DB.prepare(
          "SELECT SUM(total_cost) as cost, SUM(total_tokens) as tokens FROM cost_daily WHERE agent_id = ? AND date >= date('now', ?)"
        ).bind(agent.id, period === "7d" ? "-7 days" : period === "30d" ? "-30 days" : "-1 day").first(),

        env.DB.prepare(
          "SELECT json_extract(data, '$.job') as job, json_extract(data, '$.status') as status, COUNT(*) as count FROM events WHERE agent_id = ? AND kind = 'cron' AND ts >= ? GROUP BY job, status"
        ).bind(agent.id, sinceTs).all(),
      ]);

      return json({
        period,
        events: Object.fromEntries(eventCounts.results.map((r: any) => [r.kind, r.count])),
        cost: { usd: (costData as any)?.cost || 0, tokens: (costData as any)?.tokens || 0 },
        cron_health: cronHealth.results,
      }, 200, env);
    }

    // ── GET /v1/sessions ─────────────────────────────────────
    if (path === "/v1/sessions" && req.method === "GET") {
      const since = url.searchParams.get("since") || String(Date.now() / 1000 - 86400);
      const rows = await env.DB.prepare(
        "SELECT session_key, MIN(ts) as started, MAX(ts) as last_active, COUNT(*) as events " +
        "FROM events WHERE agent_id = ? AND session_key IS NOT NULL AND ts >= ? " +
        "GROUP BY session_key ORDER BY last_active DESC"
      ).bind(agent.id, parseFloat(since)).all();
      return json({ sessions: rows.results }, 200, env);
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
      return json({ messages: rows.results, count: rows.results.length }, 200, env);
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
      return json({ crons: rows.results }, 200, env);
    }

    return json({ error: "Not found" }, 404, env);
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
