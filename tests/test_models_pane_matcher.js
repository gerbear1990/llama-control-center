// profileForModelPath, imported from the module that ships it.
(async () => {
  const { profileForModelPath: fn } = await import('../lcc_api/static/js/matching.js');

  const winPath = 'C:\\Users\\x\\models\\Qwen3.6-27B-GGUF\\Qwen3.6-27B-Q6_K.gguf';
  const profiles = [
    { mode: 'a', launchable: true, confidence: 1.0, model: { path: winPath } },
    { mode: 'a-mtp', launchable: false, confidence: 1.0, model: { path: winPath } },
    { mode: 'b', launchable: true, confidence: 1.0, model: { path: '/home/x/models/other.gguf' } },
    { mode: 'unresolved', launchable: false, confidence: 0, model: null },
  ];

  const results = {
    exact: fn(profiles, winPath)?.mode,
    slashAgnostic: fn(profiles, 'C:/Users/x/models/Qwen3.6-27B-GGUF/Qwen3.6-27B-Q6_K.gguf')?.mode,
    caseAgnostic: fn(profiles, 'c:\\users\\x\\models\\qwen3.6-27b-gguf\\qwen3.6-27b-q6_k.gguf')?.mode,
    noMatch: fn(profiles, 'C:\\nowhere.gguf'),
  };
  const ok = results.exact === 'a' && results.slashAgnostic === 'a'
    && results.caseAgnostic === 'a' && results.noMatch === null;
  console.log(JSON.stringify({ ok, results }));
  process.exit(ok ? 0 : 1);
})();
