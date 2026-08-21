// Extracts profileForModelPath from the shipped app.js and unit-tests it.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'lcc_api', 'static', 'app.js'), 'utf8');
const start = src.indexOf('function profileForModelPath');
if (start === -1) { console.log(JSON.stringify({ ok: false, error: 'function not found' })); process.exit(1); }
// Take the function body up to the next top-level "\nfunction " declaration.
const end = src.indexOf('\nfunction ', start + 1);
const fnSrc = src.slice(start, end === -1 ? undefined : end);
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fnSrc + '; this.fn = profileForModelPath;', ctx);

const profiles = [
  { mode: 'a', launchable: true, confidence: 1.0, model: { path: 'C:\\Users\\x\\models\\Qwen3.6-27B-GGUF\\Qwen3.6-27B-Q6_K.gguf' } },
  { mode: 'a-mtp', launchable: false, confidence: 1.0, model: { path: 'C:\\Users\\x\\models\\Qwen3.6-27B-GGUF\\Qwen3.6-27B-Q6_K.gguf' } },
  { mode: 'b', launchable: true, confidence: 1.0, model: { path: '/home/x/models/other.gguf' } },
  { mode: 'unresolved', launchable: false, confidence: 0, model: null },
];

const results = {
  exact: ctx.fn(profiles, 'C:\\Users\\x\\models\\Qwen3.6-27B-GGUF\\Qwen3.6-27B-Q6_K.gguf')?.mode,
  slashAgnostic: ctx.fn(profiles, 'C:/Users/x/models/Qwen3.6-27B-GGUF/Qwen3.6-27B-Q6_K.gguf')?.mode,
  caseAgnostic: ctx.fn(profiles, 'c:\\users\\x\\models\\qwen3.6-27b-gguf\\qwen3.6-27b-q6_k.gguf')?.mode,
  noMatch: ctx.fn(profiles, 'C:\\nowhere.gguf'),
};
const ok = results.exact === 'a' && results.slashAgnostic === 'a' && results.caseAgnostic === 'a' && results.noMatch === null;
console.log(JSON.stringify({ ok, results }));
process.exit(ok ? 0 : 1);
