import { init, pulse } from './src/index.js';

// Test with debug mode, no real endpoint
const p = init({ apiKey: 'ap_test123', endpoint: 'http://localhost:9999', debug: true, agentName: 'test-agent' });

p.sessionStart('main', { model: 'opus-4-6' });
p.costEvent({ model: 'claude-opus-4-6', inputTokens: 5000, outputTokens: 1000, cost: 0.18 });
p.cronReport('backup', { status: 'ok', durationMs: 3400, summary: 'Cleaned 5 stale sessions' });
p.heartbeat({ memory_kb: 45 });
p.metric('queue_depth', 12);
p.alert('Test alert', 'info', 'Just testing');
p.memoryReport({ file: 'MEMORY.md', sizeBytes: 45000, lines: 800 });
p.sessionEnd('main');

console.log('✅ All SDK methods called successfully');
console.log(`Queue has ${(p as any).queue.length} events`);
p.destroy();
