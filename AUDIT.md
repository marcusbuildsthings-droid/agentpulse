# AgentPulse Dashboard Audit — Feb 13, 2026
Dogfooded as a real user. Every issue found.
Last updated: 14:55 PST after 3 rounds of fixes.

## 🔴 CRITICAL (Product-Breaking)

### 1. Time range filter doesn't work for costs
Cost stays $189.83 across 24h/7d/30d. Tokens and session counts barely change. The API queries aren't filtering by time range — or the data only spans 2 days so there's nothing to filter.

### 2. No session transcripts (the killer feature)
Clicking a session shows metadata and an event timeline, but no actual conversation content. "No transcript available yet." This is the ONE feature that would make the product worth paying for.

### 3. Daily Spend chart is cumulative, not daily
The "Daily Spend Trend" shows a monotonically increasing line — that's a running total, not per-day spend. Completely misleading. Should be bars per day.

### 4. Every cron job shows "Issues" (red)
All 17 jobs flagged red. If everything is broken, nothing is — this is alarm fatigue. The "Issues" status seems based on ANY failure ever, not recent health. Useless.

### 5. Cron "Last Run" is reporter timestamp, not actual job run time
All jobs show "3m ago" — that's when the reporter scraped, not when the job actually executed. Makes the cron view useless for monitoring timing.

---

## 🟡 MAJOR (Significant UX Problems)

### 6. Duplicate sessions everywhere
Same cron job appears 2-3 times (different runs). "iMessage: •••1637" appears twice in costs. Users expect grouped/aggregated views, not raw run dumps.

### 7. UUIDs still showing in Costs "Top Sessions"
The `/v1/stats` endpoint doesn't include `job_name`. Sessions page fixed, costs page still raw UUIDs.

### 8. "session:" entries cluttering Sessions view
Transcript events created phantom sessions (`session:29e7fa72...`) with 1 message and no cost. These are noise from the reporter, not real sessions.

### 9. PII masking applied to UUIDs
`session:c80ff9db-04e6-455d-a792-•••824fd` — the regex catches hex strings and masks them like phone numbers. Over-aggressive.

### 10. Duration "284m" everywhere
Many sessions show exactly 284 minutes. Likely calculated as (now - session_start) rather than (last_event - first_event). Format should be "4h 44m" not "284m".

### 11. Avg Daily cost is wrong
$94.91/day "average" on 30d view — but there's only 2 days of data. Should show actual daily average or indicate data coverage period.

### 12. No live vs archived indicator
Every session has the same grey dot. "main" is actively running, finished cron jobs from yesterday look identical. Need green/grey distinction.

---

## 🔵 MINOR (Polish & Missing Features)

### 13. Events page is a raw dump
- All transcript events at same timestamp (reporter batch)
- Raw session IDs instead of names
- No event content preview
- No filtering by event type
- Fixed 100 event cap, no pagination

### 14. Cron view missing essentials
- No duration data
- No next-run time
- No expandable run history with summaries
- Success/failure counts seem inaccurate (31 success for a job that runs 1-3x/day and has only existed for ~2 days?)

### 15. API key shown in plain text on Settings
Should be masked by default with a "show" toggle.

### 16. API endpoint URL truncated in Settings
URL cut off at "worker" — input field too narrow.

### 17. Settings page has no settings
Just connection info. No budget config, notification preferences, data retention, timezone, display preferences.

### 18. Alerts page is empty with no defaults
"No alert rules" — should auto-create sensible defaults (daily spend > $X, cron failure, gateway down).

### 19. Sparkline charts don't convey information
Green squiggles in session rows all look identical. Either make them meaningful or remove them.

### 20. "claude" model with $0.01
Legacy model entry with 100 tokens. Should be cleaned from display or filtered.

---

## 🎯 Root Cause Analysis

Most issues stem from ONE problem: **the reporter sends snapshots, not time-series data.** It scrapes current state every 15 minutes and sends it all with the same timestamp. This means:
- Time filtering can't work (data isn't tagged to when it happened)
- Cron "last run" is always reporter time
- Events all batch to same moment
- Duration is calculated wrong

**The fix:** The reporter needs to emit events as they happen (or at least backdate them correctly from the actual session/cron timestamps), and the API needs proper time-indexed queries.

The second major issue: **no transcript data at all.** The session logs exist on disk (`~/.openclaw/agents/main/sessions/*.jsonl`) but the reporter doesn't parse them into the API.

---

## Priority Fix Order
1. Fix reporter to use actual event timestamps (not send-time)
2. Build transcript extraction from .jsonl session logs
3. Fix time range filtering in API queries
4. Dedup/aggregate sessions (group cron runs by job)
5. Fix daily spend chart (bars, not cumulative line)
6. Add live/archived session indicators
7. Fix cron health status logic (recent failures, not all-time)
8. Everything else

---

## Fix Status (as of 14:55 PST)

### ✅ Fixed
1. Phantom "session:" entries — filtered from sessions view
2. Daily Spend chart — now bar chart per day
3. Cron status logic — based on actual run outcomes
4. PII masking — no longer catches UUIDs
5. Duration format — "5h 3m" instead of "284m"
6. Session dedup — cron runs grouped with "×N runs"
7. Cron "Last Run" — now real run timestamps
8. Cron durations — real values from run history
9. Cron run counts — actual runs not reporter snapshots
10. Most job names resolved in costs page
11. Session transcripts — working with real conversation data
12. Session names — all cron jobs show real names
13. Gateway Online indicator — heartbeat working

### ❌ Still Broken
1. **3 remaining UUIDs in costs** — older session keys without matching cron events. Need to parse cron UUID from session key and match against job list.
2. **Duplicate iMessage sessions** — •••1637 appears twice (different session keys for same contact)
3. **Time range filter doesn't filter cost totals** — $256 across all ranges
4. **02-12 shows $0 in daily spend** — reporter wasn't running then, so no data
5. **Events page still raw dump** — no content preview, no type filter
6. **API key plaintext on Settings** — needs mask/reveal toggle
7. **Alerts page empty** — no default rules
