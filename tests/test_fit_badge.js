// fitBadgeHtml: the Profiles table's Fit cell. A heuristic estimate must look
// like a guess, and a profile whose model file is gone must never read Good --
// both shipped as confident green badges until 2026-10-02.
(async () => {
  const assert = require('assert');
  const { fitBadgeHtml } = await import('../lcc_api/static/js/format.js');

  const exact = fitBadgeHtml({ status: 'good', basis: 'exact' });
  assert.ok(exact.includes('>Good<'), exact);
  assert.ok(!exact.includes('≈') && !exact.includes('title='), exact);

  const rough = fitBadgeHtml({ status: 'near_limit', basis: 'heuristic' });
  assert.ok(rough.includes('≈ Near Limit'), rough);
  assert.ok(rough.includes('title="Rough estimate'), rough);

  const missing = fitBadgeHtml({ status: 'missing', basis: 'heuristic' });
  assert.ok(missing.includes('>Missing file<'), missing);
  assert.ok(missing.includes('badge error'), missing);
  assert.ok(!missing.includes('≈'), missing);

  assert.ok(fitBadgeHtml(undefined).includes('Unknown'));
  console.log(JSON.stringify({ ok: true }));
})().catch((err) => { console.error(err); process.exit(1); });
