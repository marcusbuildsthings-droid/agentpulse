#!/usr/bin/env python3
"""
OpenClaw → AgentPulse Reporter
Collects data from marcus-* tools and reports to AgentPulse API.
Run via cron or manually to feed real data into AgentPulse.

Usage:
  python openclaw-reporter.py --api-key ap_dev_xxx [--url http://127.0.0.1:8787]
"""

import json
import subprocess
import time
import argparse
import urllib.request

SCRIPTS = "/Users/ape/clawd/scripts"


def run_json(cmd: str) -> dict | None:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return json.loads(r.stdout)
    except (json.JSONDecodeError, subprocess.TimeoutExpired):
        pass
    return None


def collect_sessions() -> list:
    data = run_json(f"{SCRIPTS}/marcus-sessions --json --all")
    if not data or "sessions" not in data:
        return []
    events = []
    for s in data["sessions"]:
        events.append({
            "kind": "session",
            "ts": time.time(),
            "session": s.get("key", "unknown"),
            "data": {
                "type": s.get("type", "unknown"),
                "channel": s.get("channel", "unknown"),
                "tokens": s.get("tokens", 0),
                "age_min": s.get("age_min", 0),
                "last_message": s.get("last_message", "")[:100],
            },
        })
    return events


def collect_costs() -> list:
    data = run_json(f"{SCRIPTS}/marcus-costs --json")
    if not data:
        return []
    events = []
    for s in data.get("sessions", []):
        cost = s.get("estimated_cost", 0)
        if cost > 0:
            events.append({
                "kind": "cost",
                "ts": time.time(),
                "session": s.get("key", "unknown"),
                "data": {
                    "model": s.get("model", "unknown"),
                    "input_tokens": s.get("input_tokens", 0),
                    "output_tokens": s.get("output_tokens", 0),
                    "cost": cost,
                },
            })
    if "total" in data:
        events.append({
            "kind": "metric",
            "ts": time.time(),
            "data": {
                "name": "total_cost",
                "value": data["total"].get("estimated_cost", 0),
                "total_tokens": data["total"].get("tokens", 0),
            },
        })
    return events


def collect_crons() -> list:
    data = run_json(f"{SCRIPTS}/marcus-cron --json")
    if not data or "jobs" not in data:
        return []
    events = []
    for j in data["jobs"]:
        events.append({
            "kind": "cron",
            "ts": time.time(),
            "data": {
                "job": j.get("name", "unknown"),
                "enabled": j.get("enabled", False),
                "last_status": j.get("last_status", "unknown"),
                "last_run": j.get("last_run"),
                "next_run": j.get("next_run"),
            },
        })
    return events


def collect_memory() -> list:
    data = run_json(f"{SCRIPTS}/marcus-memory --json")
    if not data:
        return []
    return [{
        "kind": "memory",
        "ts": time.time(),
        "data": {
            "memory_md_kb": data.get("memory_md", {}).get("size_kb", 0),
            "memory_md_lines": data.get("memory_md", {}).get("lines", 0),
            "session_md_age_min": data.get("session_md", {}).get("age_min"),
            "today_log_lines": data.get("today", {}).get("lines", 0),
            "total_files": data.get("total", {}).get("files", 0),
        },
    }]


def collect_health() -> list:
    data = run_json(f"{SCRIPTS}/marcus-health --json")
    if not data:
        return []
    return [{
        "kind": "heartbeat",
        "ts": time.time(),
        "data": {
            "healthy": data.get("healthy", False),
            "checks": data.get("checks", {}),
            "issues": data.get("issues", []),
        },
    }]


def send_events(url: str, api_key: str, events: list) -> bool:
    if not events:
        return True
    payload = json.dumps({"events": events}).encode()
    req = urllib.request.Request(
        f"{url}/v1/ingest",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            print(f"  Sent {len(events)} events → accepted: {result.get('accepted', 0)}")
            return True
    except Exception as e:
        print(f"  Failed to send: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="OpenClaw → AgentPulse Reporter")
    parser.add_argument("--api-key", required=True, help="AgentPulse API key (ap_...)")
    parser.add_argument("--url", default="http://127.0.0.1:8787", help="AgentPulse API URL")
    parser.add_argument("--dry-run", action="store_true", help="Collect but don't send")
    args = parser.parse_args()

    collectors = [
        ("sessions", collect_sessions),
        ("costs", collect_costs),
        ("crons", collect_crons),
        ("memory", collect_memory),
        ("health", collect_health),
    ]

    all_events = []
    for name, fn in collectors:
        print(f"Collecting {name}...")
        events = fn()
        print(f"  → {len(events)} events")
        all_events.extend(events)

    print(f"\nTotal: {len(all_events)} events")

    if args.dry_run:
        print("\n[dry-run] Events:")
        for e in all_events:
            print(f"  {e['kind']}: {json.dumps(e['data'])[:120]}")
    else:
        send_events(args.url, args.api_key, all_events)


if __name__ == "__main__":
    main()
