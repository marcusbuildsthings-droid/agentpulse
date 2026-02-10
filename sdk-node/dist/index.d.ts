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
export interface PulseEvent {
    kind: string;
    ts: number;
    data: Record<string, unknown>;
    agent: string;
    session: string;
}
export interface InitOptions {
    apiKey?: string;
    endpoint?: string;
    agentName?: string;
    flushIntervalMs?: number;
    enabled?: boolean;
    debug?: boolean;
}
export interface CostEventOptions {
    model: string;
    inputTokens?: number;
    outputTokens?: number;
    cost?: number;
    session?: string;
}
export interface CronReportOptions {
    status?: string;
    durationMs?: number;
    summary?: string;
}
export interface MemoryReportOptions {
    file: string;
    sizeBytes: number;
    lines?: number;
}
export declare class AgentPulse {
    private apiKey;
    private endpoint;
    private agentName;
    private enabled;
    private debug;
    private queue;
    private activeSessions;
    private timer;
    constructor(opts?: InitOptions);
    sessionStart(key: string, metadata?: Record<string, unknown>): void;
    sessionEnd(key: string, metadata?: Record<string, unknown>): void;
    sessionEvent(key: string, eventType: string, data?: Record<string, unknown>): void;
    costEvent(opts: CostEventOptions): void;
    cronReport(jobName: string, opts?: CronReportOptions): void;
    heartbeat(metadata?: Record<string, unknown>): void;
    metric(name: string, value: number, tags?: Record<string, string>): void;
    alert(title: string, severity?: 'info' | 'warning' | 'critical', details?: string): void;
    memoryReport(opts: MemoryReportOptions): void;
    flush(): Promise<number>;
    destroy(): void;
    private enqueue;
}
export declare let pulse: AgentPulse;
export declare function init(opts?: InitOptions): AgentPulse;
