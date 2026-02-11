#!/usr/bin/env python3
"""
AgentPulse Local Dev Server
Same API as Cloudflare Worker but runs locally with SQLite.
Usage: python dev-server.py [--port 8787] [--db agentpulse.db]
"""

import json
import sqlite3
import time
import argparse
import secrets
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

DB_PATH = "agentpulse.db"
VERSION = "0.1.0-dev"


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    schema = (Path(__file__).parent / "schema.sql").read_text()
    conn.executescript(schema)
    # Ensure a default agent exists for dogfooding
    row = conn.execute("SELECT id FROM agents WHERE name='marcus'").fetchone()
    if not row:
        key = "ap_dev_" + secrets.token_hex(16)
        conn.execute(
            "INSERT INTO agents (name, api_key, plan) VALUES (?, ?, ?)",
            ("marcus", key, "pro"),
        )
        conn.commit()
        print(f"Created default agent 'marcus' with key: {key}")
    else:
        key = conn.execute("SELECT api_key FROM agents WHERE name='marcus'").fetchone()["api_key"]
        print(f"Existing agent 'marcus' key: {key}")
    return conn


class Handler(BaseHTTPRequestHandler):
    conn: sqlite3.Connection = None  # set after init

    def _cors(self):
        return {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
        }

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in self._cors().items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ap_"):
            return None
        key = auth[7:]
        row = self.conn.execute(
            "SELECT id, name FROM agents WHERE api_key = ?", (key,)
        ).fetchone()
        return dict(row) if row else None

    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in self._cors().items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/v1/health":
            self._json({"status": "ok", "version": VERSION})
            return

        agent = self._auth()
        if not agent:
            self._json({"error": "Unauthorized"}, 401)
            return

        aid = agent["id"]

        if path == "/v1/events":
            kind = qs.get("kind", [None])[0]
            limit = int(qs.get("limit", ["100"])[0])
            since = float(qs.get("since", ["0"])[0])
            sql = "SELECT id, kind, ts, session_key, data FROM events WHERE agent_id = ? AND ts > ?"
            params = [aid, since]
            if kind:
                sql += " AND kind = ?"
                params.append(kind)
            sql += " ORDER BY ts DESC LIMIT ?"
            params.append(limit)
            rows = self.conn.execute(sql, params).fetchall()
            events = []
            for r in rows:
                e = dict(r)
                e["data"] = json.loads(e["data"])
                events.append(e)
            self._json({"events": events, "count": len(events)})

        elif path == "/v1/stats":
            period = qs.get("period", ["24h"])[0]
            hours = 24
            if period.endswith("h"):
                hours = int(period[:-1])
            elif period.endswith("d"):
                hours = int(period[:-1]) * 24
            since = time.time() - hours * 3600

            total = self.conn.execute(
                "SELECT COUNT(*) as c FROM events WHERE agent_id = ? AND ts > ?",
                (aid, since),
            ).fetchone()["c"]

            by_kind = self.conn.execute(
                "SELECT kind, COUNT(*) as c FROM events WHERE agent_id = ? AND ts > ? GROUP BY kind",
                (aid, since),
            ).fetchall()

            costs = self.conn.execute(
                "SELECT SUM(json_extract(data, '$.cost')) as total_cost, "
                "SUM(json_extract(data, '$.input_tokens') + json_extract(data, '$.output_tokens')) as total_tokens "
                "FROM events WHERE agent_id = ? AND kind = 'cost' AND ts > ?",
                (aid, since),
            ).fetchone()

            # Cron health aggregation
            cron_health_rows = self.conn.execute(
                "SELECT json_extract(data, '$.job') as job, json_extract(data, '$.status') as status, COUNT(*) as count "
                "FROM events WHERE agent_id = ? AND kind = 'cron' AND ts > ? "
                "GROUP BY job, status",
                (aid, since),
            ).fetchall()
            cron_health = [{"job": r["job"], "status": r["status"], "count": r["count"]} for r in cron_health_rows]

            self._json({
                "period": period,
                "total_events": total,
                "events": {r["kind"]: r["c"] for r in by_kind},
                "cost": {
                    "usd": costs["total_cost"] or 0,
                    "tokens": costs["total_tokens"] or 0,
                },
                "cron_health": cron_health,
            })

        elif path == "/v1/sessions":
            since = float(qs.get("since", [str(time.time() - 86400)])[0])
            rows = self.conn.execute(
                "SELECT DISTINCT session_key, MIN(ts) as started, MAX(ts) as last_active, COUNT(*) as events "
                "FROM events WHERE agent_id = ? AND session_key IS NOT NULL AND ts > ? "
                "GROUP BY session_key ORDER BY last_active DESC",
                (aid, since),
            ).fetchall()
            self._json({"sessions": [dict(r) for r in rows]})

        elif path == "/v1/crons":
            rows = self.conn.execute(
                "SELECT json_extract(data, '$.job') as job, kind, ts, "
                "json_extract(data, '$.status') as status, "
                "json_extract(data, '$.duration_ms') as duration_ms "
                "FROM events WHERE agent_id = ? AND kind = 'cron' "
                "ORDER BY ts DESC LIMIT 50",
                (aid,),
            ).fetchall()
            self._json({"crons": [dict(r) for r in rows]})

        else:
            self._json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        # Register — no auth required
        if path == "/v1/register":
            name = body.get("name", "")
            if len(name) < 2:
                self._json({"error": "Name required (min 2 chars)"}, 400)
                return
            email = body.get("email")
            key = "ap_" + secrets.token_hex(16)
            try:
                self.conn.execute(
                    "INSERT INTO agents (name, api_key, email, plan) VALUES (?, ?, ?, 'free')",
                    (name, key, email),
                )
                self.conn.commit()
                self._json({"name": name, "api_key": key, "plan": "free"}, 201)
            except sqlite3.IntegrityError:
                self._json({"error": "Name or email already registered"}, 409)
            return

        # Auth required below
        agent = self._auth()
        if not agent:
            self._json({"error": "Unauthorized"}, 401)
            return

        if path == "/v1/ingest":
            events = body.get("events", [])
            if not events:
                self._json({"error": "No events"}, 400)
                return

            inserted = 0
            for ev in events:
                kind = ev.get("kind", "unknown")
                ts = ev.get("ts", time.time())
                session = ev.get("session")
                data = ev.get("data", {})
                self.conn.execute(
                    "INSERT INTO events (agent_id, kind, ts, session_key, data) VALUES (?, ?, ?, ?, ?)",
                    (agent["id"], kind, ts, session, json.dumps(data)),
                )
                # Update cost_daily if cost event
                if kind == "cost" and "cost" in data:
                    from datetime import datetime, timezone
                    date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                    tokens = data.get("input_tokens", 0) + data.get("output_tokens", 0)
                    self.conn.execute(
                        "INSERT INTO cost_daily (agent_id, date, total_cost, total_tokens, event_count) "
                        "VALUES (?, ?, ?, ?, 1) "
                        "ON CONFLICT(agent_id, date) DO UPDATE SET "
                        "total_cost = total_cost + ?, total_tokens = total_tokens + ?, event_count = event_count + 1",
                        (agent["id"], date, data["cost"], tokens, data["cost"], tokens),
                    )
                inserted += 1
            self.conn.commit()
            self._json({"accepted": inserted})

        else:
            self._json({"error": "Not found"}, 404)

    def log_message(self, format, *args):
        # Quieter logging
        pass


def main():
    parser = argparse.ArgumentParser(description="AgentPulse Dev Server")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--db", default="agentpulse.db")
    args = parser.parse_args()

    conn = init_db(args.db)
    Handler.conn = conn

    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"AgentPulse dev server on http://127.0.0.1:{args.port}")
    print(f"DB: {args.db}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()


if __name__ == "__main__":
    main()
