// buildServerMetricsRows: the panel companion to formatServerMetricsLine.
// Absent fields must be DROPPED, not rendered -- server_metrics returns null
// for llama.cpp-only fields when the server is vLLM, and "NaN%" on screen
// reads as a broken app rather than an absent reading.
const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'lcc_api', 'static', 'app.js'), 'utf8');
const fn = src.match(/function buildServerMetricsRows[\s\S]*?\n}/);
if (!fn) {
  console.log(JSON.stringify({ ok: false, error: 'buildServerMetricsRows not found' }));
  process.exit(1);
}
const formatBytes = (b) => `${b}B`;
eval(fn[0]);

const label = (rows, name) => rows.find((r) => r.label === name);

// Full llama.cpp payload
const full = buildServerMetricsRows({
  summary: { kv_cache_usage_ratio: 0.42, kv_cache_tokens: 1234, slots_active: 1,
             slots_processing: 2, predicted_tokens_per_second: 33.33,
             prompt_tokens_per_second: 120.5 },
  process: { rss_bytes: 100, gpu_used_bytes: 200, cpu_percent: 12.6 },
  props: { n_ctx: 4096, model_name: 'Qwen', build_info: 'b10472' },
  health: 'ok',
});
const kv = label(full, 'KV cache');
const kvOk = kv && kv.value === '42%' && Math.abs(kv.ratio - 0.42) < 1e-9;
const decodeOk = label(full, 'Decode').value === '33.3 t/s';
const slotsOk = label(full, 'Slots').value === '1 active / 2 processing';
const cpuOk = label(full, 'CPU').value === '13%';
const healthOk = !!label(full, 'Health');

// vLLM-ish payload: llama.cpp-only fields absent
const sparse = buildServerMetricsRows({ summary: {}, process: { rss_bytes: 10 }, props: {} });
const noNulls = sparse.every((r) => r.value !== null && r.value !== undefined
  && !String(r.value).includes('NaN') && !String(r.value).includes('null'));
const dropsAbsent = !label(sparse, 'KV cache') && !label(sparse, 'Slots') && !!label(sparse, 'Process RSS');

// health: 'unknown' is a placeholder, not a reading
const unknownHealth = buildServerMetricsRows({ summary: {}, process: {}, props: {}, health: 'unknown' });
const hidesUnknown = !label(unknownHealth, 'Health');

const emptyOk = buildServerMetricsRows(null).length === 0
  && buildServerMetricsRows(undefined).length === 0;

const ok = kvOk && decodeOk && slotsOk && cpuOk && healthOk && noNulls
  && dropsAbsent && hidesUnknown && emptyOk;
console.log(JSON.stringify({ ok, kvOk, decodeOk, slotsOk, cpuOk, healthOk,
  noNulls, dropsAbsent, hidesUnknown, emptyOk, rows: full.length }));
process.exit(ok ? 0 : 1);
