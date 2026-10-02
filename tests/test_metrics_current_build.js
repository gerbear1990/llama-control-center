// buildServerMetricsRows against what llama-server b10752 actually returns:
// only a busy-slot count (no "active"), and no /metrics at all on a server
// started without --metrics. Both rendered as silence or "0 active" before.
(async () => {
  const assert = require('assert');
  const { buildServerMetricsRows } = await import('../lcc_api/static/js/format.js');
  const label = (rows, name) => rows.find((r) => r.label === name);

  const current = buildServerMetricsRows({
    summary: { slots_processing: 1, predicted_tokens_per_second: 59.7 },
    process: {}, props: { n_ctx: 131072, total_slots: 4 }, metrics_available: true,
  });
  assert.strictEqual(label(current, 'Slots').value, '1 busy of 4');
  assert.strictEqual(label(current, 'Decode').value, '59.7 t/s');
  assert.strictEqual(label(current, 'Context').value, '131072');
  assert.ok(!label(current, 'Metrics'));

  const off = buildServerMetricsRows({ summary: {}, process: {}, props: {}, metrics_available: false });
  assert.ok(label(off, 'Metrics').value.startsWith('Off'));

  // Older payloads without the flag must not grow a warning row.
  assert.ok(!label(buildServerMetricsRows({ summary: {}, process: {}, props: {} }), 'Metrics'));
  console.log(JSON.stringify({ ok: true }));
})().catch((err) => { console.error(err); process.exit(1); });
