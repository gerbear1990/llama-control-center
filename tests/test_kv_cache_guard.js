// KV-cache mismatch copy: CUDA has no FA kernel for mixed -ctk/-ctv.
const path = require('path');

(async () => {
  const { kvCacheMismatchNote } = await import('../lcc_api/static/js/launch.js');

  const mixed = kvCacheMismatchNote('f16', 'q8_0');
  const matched = kvCacheMismatchNote('q8_0', 'q8_0');
  const cpu = kvCacheMismatchNote('f16', 'q8_0', { acceleration: 'cpu' });
  const empty = kvCacheMismatchNote('', 'q8_0');

  const ok = (
    typeof mixed === 'string'
    && mixed.includes('f16')
    && mixed.includes('q8_0')
    && /flash-attn|CPU/i.test(mixed)
    && matched === ''
    && cpu === ''
    && empty === ''
  );

  console.log(JSON.stringify({ ok, mixed: mixed.slice(0, 80), matched, cpu, empty }));
  process.exit(ok ? 0 : 1);
})();
