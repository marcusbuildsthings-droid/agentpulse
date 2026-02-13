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
    
    # Get cron job ID to name mapping
    cron_data = run_json(f"{SCRIPTS}/marcus-cron --json")
    cron_id_to_name = {}
    if cron_data:
        for job in cron_data:
            if job.get("id") and job.get("name"):
                cron_id_to_name[job["id"]] = job["name"]
    
    events = []
    for s in data["sessions"]:
        session_key = s.get("key", "unknown")
        
        # Extract job name from cron sessions using ID mapping
        job_name = None
        if ":cron:" in session_key:
            parts = session_key.split(":cron:")
            if len(parts) > 1:
                cron_part = parts[1].split(":")[0]  # Get first part after :cron:
                # Try to map UUID to job name
                job_name = cron_id_to_name.get(cron_part, cron_part)
        
        session_data = {
            "type": s.get("type", "unknown"),
            "channel": s.get("channel", "unknown"),
            "tokens": s.get("tokens", 0),
            "age_min": s.get("age_min", 0),
            "last_message": s.get("last_message", "")[:100],
        }
        
        # Add job name for cron sessions
        if job_name:
            session_data["job_name"] = job_name
        
        events.append({
            "kind": "session",
            "ts": time.time(),
            "session": session_key,
            "data": session_data,
        })
    return events


def collect_costs() -> list:
    data = run_json(f"{SCRIPTS}/marcus-costs --json")
    if not data:
        return []
    events = []
    for s in data.get("sessions", []):
        tokens = s.get("tokens") or 0
        if tokens > 0:
            # Estimate cost from tokens if not provided (rough Claude estimate)
            cost = s.get("cost", 0) or s.get("estimated_cost", 0)
            session_key = s.get("key", "unknown")
            events.append({
                "kind": "cost",
                "ts": time.time(),
                "session": session_key,  # This populates the session_key field
                "data": {
                    "model": s.get("model", "unknown"),
                    "input_tokens": s.get("input_tokens", 0),
                    "output_tokens": s.get("output_tokens", 0),
                    "tokens": tokens,
                    "cost_usd": cost,
                    "session_key": session_key,  # Also include in data for compatibility
                },
            })
    if "totals" in data:  # Fixed: was "total", should be "totals" based on marcus-costs output
        events.append({
            "kind": "metric",
            "ts": time.time(),
            "data": {
                "name": "total_cost",
                "value": data["totals"].get("estimatedCost", 0),
                "total_tokens": data["totals"].get("totalTokens", 0),
            },
        })
    return events


def collect_crons() -> list:
    data = run_json(f"{SCRIPTS}/marcus-cron --json")
    if not data or "jobs" not in data:
        return []
    events = []
    for j in data["jobs"]:
        job_name = j.get("name")
        # Skip jobs with null/None names to avoid garbage data
        if not job_name or job_name == "null":
            continue
        events.append({
            "kind": "cron",
            "ts": time.time(),
            "data": {
                "job": job_name,
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


def send_heartbeat(url: str, api_key: str) -> bool:
    """Report gateway liveness to AgentPulse."""
    req = urllib.request.Request(
        f"{url}/v1/heartbeat",
        data=b"{}",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            json.loads(resp.read())
            print("  Heartbeat sent ✓")
            return True
    except Exception as e:
        print(f"  Heartbeat failed: {e}")
        return False


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
            "User-Agent": "openclaw-reporter/1.0",
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
        print("Sending heartbeat...")
        send_heartbeat(args.url, args.api_key)
        send_events(args.url, args.api_key, all_events)


if __name__ == "__main__":
    main()
