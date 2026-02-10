/**
 * AgentPulse Node.js SDK — zero-dependency, fire-and-forget monitoring.
 *
 * Usage:
 *   import { init, pulse } from 'agentpulse';
 *   init({ apiKey: 'ap_...' });
 *   pulse.sessionStart('main');
 *   pulse.costEvent({ model: 'claude-opus-4', inputTokens: 5000, cost: 0.15 });
 *   pulse.cronReport('backup', { status: 'ok', durationMs: 3400 });
 */
import os from 'node:os';
const DEFAULT_ENDPOINT = 'https://api.agentpulse.dev';
const FLUSH_INTERVAL_MS = 10_000;
const BATCH_SIZE = 500;
const QUEUE_MAX = 5_000;
// ── Client ──────────────────────────────────────────────────
export class AgentPulse {
    apiKey;
    endpoint;
    agentName;
    enabled;
    debug;
    queue = [];
    activeSessions = new Map();
    timer = null;
    constructor(opts = {}) {
        this.apiKey = opts.apiKey ?? process.env.AGENTPULSE_API_KEY ?? '';
        this.endpoint = (opts.endpoint ?? process.env.AGENTPULSE_ENDPOINT ?? DEFAULT_ENDPOINT).replace(/\/$/, '');
        this.agentName = opts.agentName ?? process.env.AGENTPULSE_AGENT ?? os.hostname();
        this.enabled = (opts.enabled ?? true) && !!this.apiKey;
        this.debug = opts.debug ?? false;
        if (this.enabled) {
            const interval = opts.flushIntervalMs ?? FLUSH_INTERVAL_MS;
            this.timer = setInterval(() => this.flush(), interval);
            this.timer.unref(); // Don't keep process alive
            process.on('beforeExit', () => this.flush());
        }
    }
    // ── Public API ──────────────────────────────────────────
    sessionStart(key, metadata) {
        this.activeSessions.set(key, Date.now());
        this.enqueue('session', { action: 'start', ...metadata }, key);
    }
    sessionEnd(key, metadata) {
        const start = this.activeSessions.get(key);
        this.activeSessions.delete(key);
        const durationMs = start ? Date.now() - start : undefined;
        this.enqueue('session', { action: 'end', duration_ms: durationMs, ...metadata }, key);
    }
    sessionEvent(key, eventType, data) {
        this.enqueue('session', { action: eventType, ...data }, key);
    }
    costEvent(opts) {
        this.enqueue('cost', {
            model: opts.model,
            input_tokens: opts.inputTokens ?? 0,
            output_tokens: opts.outputTokens ?? 0,
            cost_usd: opts.cost,
        }, opts.session ?? '');
    }
    cronReport(jobName, opts = {}) {
        this.enqueue('cron', {
            job: jobName,
            status: opts.status ?? 'ok',
            duration_ms: opts.durationMs,
            summary: opts.summary,
        });
    }
    heartbeat(metadata) {
        this.enqueue('heartbeat', {
            active_sessions: this.activeSessions.size,
            ...metadata,
        });
    }
    metric(name, value, tags) {
        this.enqueue('metric', { name, value, tags: tags ?? {} });
    }
    alert(title, severity = 'warning', details) {
        this.enqueue('alert', { title, severity, details });
    }
    memoryReport(opts) {
        this.enqueue('memory', {
            file: opts.file,
            size_bytes: opts.sizeBytes,
            lines: opts.lines,
        });
    }
    // ── Flush ─────────────────────────────────────────────
    async flush() {
        if (!this.queue.length)
            return 0;
        const batch = this.queue.splice(0, BATCH_SIZE * 10);
        try {
            const res = await fetch(`${this.endpoint}/v1/ingest`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${this.apiKey}`,
                    'User-Agent': 'agentpulse-node/0.1.0',
                },
                body: JSON.stringify({ agent: this.agentName, events: batch }),
                signal: AbortSignal.timeout(10_000),
            });
            if (!res.ok && this.debug) {
                console.error(`[agentpulse] flush failed: ${res.status}`);
            }
            return batch.length;
        }
        catch (err) {
            if (this.debug)
                console.error(`[agentpulse] flush error:`, err);
            // Re-queue on failure (best effort)
            const requeue = batch.slice(0, QUEUE_MAX / 2);
            this.queue.unshift(...requeue);
            return 0;
        }
    }
    destroy() {
        if (this.timer)
            clearInterval(this.timer);
        this.flush();
    }
    // ── Internal ──────────────────────────────────────────
    enqueue(kind, data, session = '') {
        if (!this.enabled)
            return;
        if (this.queue.length >= QUEUE_MAX) {
            if (this.debug)
                console.warn('[agentpulse] queue full, dropping event');
            return;
        }
        this.queue.push({
            kind,
            ts: Date.now() / 1000,
            data,
            agent: this.agentName,
            session,
        });
    }
}
// ── Module singleton ────────────────────────────────────────
export let pulse = new AgentPulse();
export function init(opts = {}) {
    pulse = new AgentPulse(opts);
    return pulse;
}
