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
        
        # Get sub-agent label if available
        label = s.get("label")
        
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
        
        # Add label for sub-agent sessions
        if label:
            session_data["label"] = label
        
        events.append({
            "kind": "session",
            "ts": time.time(),
            "session": session_key,
            "data": session_data,
        })
    
    # Also emit session events for all known cron UUIDs so API can resolve names
    # even for sessions that aren't currently active
    seen_cron_uuids = set()
    for e in events:
        if ":cron:" in e.get("session", ""):
            parts = e["session"].split(":cron:")
            if len(parts) > 1:
                seen_cron_uuids.add(parts[1].split(":")[0])
    
    for cron_id, cron_name in cron_id_to_name.items():
        if cron_id not in seen_cron_uuids:
            cron_key = f"agent:main:cron:{cron_id}"
            events.append({
                "kind": "session",
                "ts": time.time(),
                "session": cron_key,
                "data": {
                    "type": "cron",
                    "channel": "cron",
                    "tokens": 0,
                    "age_min": 0,
                    "last_message": "",
                    "job_name": cron_name,
                },
            })
    
    return events


def collect_costs() -> list:
    """Collect cost DELTAS — only report new spend since last run."""
    COST_STATE = "/tmp/agentpulse-cost-state.json"
    
    # Load previous cost state
    prev_costs = {}
    try:
        with open(COST_STATE, "r") as f:
            prev_costs = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    
    data = run_json(f"{SCRIPTS}/marcus-costs --json")
    if not data:
        return []
    
    events = []
    new_costs = {}
    
    for s in data.get("sessions", []):
        tokens = s.get("tokens") or 0
        cost = s.get("cost", 0) or s.get("estimated_cost", 0) or 0
        session_key = s.get("key", "unknown")
        
        if tokens <= 0:
            continue
        
        # Store current totals for next run
        new_costs[session_key] = {"tokens": tokens, "cost": cost}
        
        # Calculate delta from last report
        prev = prev_costs.get(session_key, {"tokens": 0, "cost": 0})
        delta_tokens = max(0, tokens - prev.get("tokens", 0))
        delta_cost = max(0, cost - prev.get("cost", 0))
        
        # Only emit event if there's new spend
        if delta_tokens > 0 or delta_cost > 0:
            events.append({
                "kind": "cost",
                "ts": time.time(),
                "session": session_key,
                "data": {
                    "model": s.get("model", "unknown"),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "tokens": delta_tokens,
                    "cost_usd": round(delta_cost, 6),
                    "session_key": session_key,
                },
            })
    
    # Save current state for next run
    try:
        with open(COST_STATE, "w") as f:
            json.dump(new_costs, f)
    except Exception:
        pass
    
    if "totals" in data:
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
    """Collect ACTUAL cron run history, not just job status snapshots.
    Uses marcus-cron runs <job> --json to get real run data.
    Tracks last reported timestamp to avoid duplicates.
    """
    STATE_FILE = "/tmp/agentpulse-reporter-state.json"

    # Load state
    last_reported = {}
    try:
        with open(STATE_FILE, "r") as f:
            state = json.loads(f.read())
            last_reported = state.get("last_reported_ts", {})
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Get all job names
    data = run_json(f"{SCRIPTS}/marcus-cron --json")
    if not data:
        return []
    jobs = data if isinstance(data, list) else data.get("jobs", [])

    events = []
    new_last_reported = dict(last_reported)

    for j in jobs:
        job_name = j.get("name")
        if not job_name or job_name == "null":
            continue

        # Get actual run history for this job
        runs = run_json(f"{SCRIPTS}/marcus-cron runs {job_name} --json")
        if not runs or not isinstance(runs, list):
            continue

        cutoff_ts = last_reported.get(job_name, 0)
        max_ts = cutoff_ts

        for run in runs:
            run_ts = run.get("ts", 0)
            if isinstance(run_ts, (int, float)):
                run_ts_sec = run_ts / 1000.0  # ms to seconds
            else:
                continue

            # Skip already-reported runs
            if run_ts <= cutoff_ts:
                continue

            # Only include finished runs
            if run.get("action") != "finished":
                continue

            status = run.get("status", "unknown")  # "ok" or "error"
            started_at = run.get("runAtMs")
            if started_at:
                started_at = started_at / 1000.0

            events.append({
                "kind": "cron",
                "ts": run_ts_sec,
                "data": {
                    "job": job_name,
                    "status": status,
                    "started_at": started_at,
                    "duration_ms": run.get("durationMs"),
                    "summary": (run.get("summary") or "")[:500],
                    "error": (run.get("error") or "")[:500] if status == "error" else None,
                },
            })

            if run_ts > max_ts:
                max_ts = run_ts

        if max_ts > cutoff_ts:
            new_last_reported[job_name] = max_ts

    # Save state
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"last_reported_ts": new_last_reported}, f)
    except Exception:
        pass

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


def collect_transcripts() -> list:
    """Read session .jsonl files and extract transcript messages."""
    import glob
    import os
    
    sessions_dir = os.path.expanduser("~/.openclaw/agents/main/sessions")
    if not os.path.isdir(sessions_dir):
        return []
    
    events = []
    # Get active sessions from marcus-sessions to know which ones to read
    data = run_json(f"{SCRIPTS}/marcus-sessions --json --all")
    if not data or "sessions" not in data:
        return []
    
    # Build sessionId → session_key map
    uuid_to_key = {}
    for s in data.get("sessions", []):
        sid = s.get("sessionId", "")
        sk = s.get("key", "")
        if sid and sk:
            uuid_to_key[sid] = sk
    
    # Scan all recent .jsonl files (modified in last 24h)
    now = time.time()
    jsonl_files = glob.glob(os.path.join(sessions_dir, "*.jsonl"))
    
    for fpath in jsonl_files:
        try:
            # Only process files modified in last 24 hours
            mtime = os.path.getmtime(fpath)
            if now - mtime > 86400:
                continue
            
            messages = []
            session_key = None
            
            with open(fpath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    
                    etype = entry.get("type")
                    
                    # Extract session key from session entry
                    if etype == "session":
                        # Try to find the session key from the data
                        # The file UUID is in entry["id"]
                        pass
                    
                    # Extract messages
                    if etype == "message" and "message" in entry:
                        msg = entry["message"]
                        role = msg.get("role", "")
                        ts = entry.get("timestamp", "")
                        content_parts = msg.get("content", [])
                        
                        if role == "user":
                            # Extract text from user messages
                            text = ""
                            for part in (content_parts if isinstance(content_parts, list) else []):
                                if isinstance(part, dict) and part.get("type") == "text":
                                    text += part.get("text", "")
                                elif isinstance(part, str):
                                    text += part
                            if text.strip():
                                # Strip timestamp prefixes like "[Fri 2026-02-13 08:08 PST]"
                                import re
                                text = re.sub(r'^\[.*?\]\s*', '', text.strip())
                                messages.append({
                                    "role": "user",
                                    "content": text[:500],
                                    "ts": ts,
                                })
                        
                        elif role == "assistant":
                            text = ""
                            tool_calls = []
                            for part in (content_parts if isinstance(content_parts, list) else []):
                                if isinstance(part, dict):
                                    if part.get("type") == "text":
                                        t = part.get("text", "").strip()
                                        if t:
                                            text += t
                                    elif part.get("type") == "toolCall":
                                        tool_calls.append(part.get("name", "unknown"))
                            
                            if text.strip():
                                messages.append({
                                    "role": "assistant",
                                    "content": text[:500],
                                    "ts": ts,
                                })
                            if tool_calls:
                                messages.append({
                                    "role": "tool_call",
                                    "content": ", ".join(tool_calls),
                                    "ts": ts,
                                })
                        
                        elif role == "toolResult":
                            tool_name = msg.get("toolName", "unknown")
                            # Get a brief summary of the result
                            result_text = ""
                            for part in (content_parts if isinstance(content_parts, list) else []):
                                if isinstance(part, dict) and part.get("type") == "text":
                                    result_text += part.get("text", "")
                            if result_text:
                                result_text = result_text[:300]
                            messages.append({
                                "role": "tool_result",
                                "content": f"{tool_name}: {result_text}" if result_text else tool_name,
                                "ts": ts,
                            })
            
            if not messages:
                continue
            
            # Determine session key from the file
            # Try to match by reading the session entry in the file
            file_uuid = os.path.basename(fpath).replace(".jsonl", "")
            
            # Read first line to get session info
            with open(fpath, 'r') as f:
                first_line = f.readline().strip()
                try:
                    first = json.loads(first_line)
                    if first.get("type") == "session":
                        # The session key might be derivable from context
                        # For now use a constructed key
                        pass
                except:
                    pass
            
            # Match file UUID to session key via the map we built
            matched_key = uuid_to_key.get(file_uuid, f"session:{file_uuid}")
            
            # Limit to last 50 messages to keep payload small
            messages = messages[-50:]
            
            events.append({
                "kind": "transcript",
                "ts": time.time(),
                "session": matched_key,
                "data": {
                    "session_key": matched_key,
                    "messages": messages,
                    "message_count": len(messages),
                },
            })
        
        except Exception as e:
            print(f"  Error reading {fpath}: {e}")
            continue
    
    return events


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
            "User-Agent": "AgentPulse-Reporter/1.0",
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
    # Send in batches of 80 to stay under 256KB limit
    BATCH_SIZE = 80
    total_accepted = 0
    for i in range(0, len(events), BATCH_SIZE):
        batch = events[i:i+BATCH_SIZE]
        payload = json.dumps({"events": batch}).encode()
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
                accepted = result.get('accepted', 0)
                total_accepted += accepted
                print(f"  Sent batch {i//BATCH_SIZE+1} ({len(batch)} events) → accepted: {accepted}")
        except Exception as e:
            print(f"  Failed to send batch {i//BATCH_SIZE+1}: {e}")
            return False
    print(f"  Total accepted: {total_accepted}")
    return True


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
        ("transcripts", collect_transcripts),
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
