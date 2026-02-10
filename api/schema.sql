-- AgentPulse D1 Schema

CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    api_key TEXT NOT NULL UNIQUE,
    email TEXT,
    plan TEXT DEFAULT 'free',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(email)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    kind TEXT NOT NULL,  -- session, cron, cost, heartbeat, metric, memory, alert
    ts REAL NOT NULL,
    session_key TEXT,
    data TEXT NOT NULL DEFAULT '{}',  -- JSON
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_agent_kind ON events(agent_id, kind, ts);
CREATE INDEX IF NOT EXISTS idx_events_agent_session ON events(agent_id, session_key, ts);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

CREATE TABLE IF NOT EXISTS cost_daily (
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    date TEXT NOT NULL,
    total_cost REAL DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    event_count INTEGER DEFAULT 0,
    PRIMARY KEY (agent_id, date)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    rule_name TEXT NOT NULL,
    condition TEXT NOT NULL,  -- JSON: {metric, op, threshold}
    channel TEXT DEFAULT 'email',  -- email, webhook
    webhook_url TEXT,
    enabled INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Retention: free=7 days, pro=90 days. Run cleanup via scheduled worker.
