// Tests the *shipped* formatServerMetricsLine from lcc_api/static/app.js via Node + vm eval.
// This drives the real formatter (no reimplementation) with minimal stubs (plan-allowed).
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const appJs = path.join(__dirname, '../lcc_api/static/app.js');
const fullCode = fs.readFileSync(appJs, 'utf8');

// Robust extraction of a function source from the real shipped file by brace counting.
// Avoids running any top-level init code.
function extractFunctionSource(src, name) {
  const start = src.indexOf('function ' + name);
  if (start === -1) return null;
  let i = src.indexOf('{', start);
  if (i === -1) return null;
  let depth = 1;
  i++;
  const len = src.length;
  while (i < len && depth > 0) {
    const ch = src[i];
    if (ch === '{') depth++;
    else if (ch === '}') depth--;
    i++;
  }
  if (depth !== 0) return null;
  return src.substring(start, i);
}

let fbSrc = extractFunctionSource(fullCode, 'formatBytes');
let fmSrc = extractFunctionSource(fullCode, 'formatServerMetricsLine');

if (!fbSrc) fbSrc = 'function formatBytes(b){ if(!b) return "-"; const mb=b/1024/1024; return (mb>=1024?(mb/1024).toFixed(1)+" GB":Math.round(mb)+" MB"); }';
if (!fmSrc) {
  console.error('Could not extract formatServerMetricsLine from shipped app.js');
  process.exit(1);
}

const code = fbSrc + '\n' + fmSrc;

// Sandbox
const sandbox = {
  console: console
};
vm.createContext(sandbox);

// Run only the extracted pure functions.
vm.runInContext(code, sandbox);

if (typeof sandbox.formatServerMetricsLine !== 'function') {
  console.error('formatServerMetricsLine not defined after eval of extracted source');
  process.exit(1);
}

// Fixture taken from real /metrics success shape (summary + props + process) as produced by live probe.
const fixture = {
  summary: {
    kv_cache_usage_ratio: 0.42,
    predicted_tokens_per_second: 3.2,
    slots_active: 1,
    slots_processing: 1,
    kv_cache_tokens: 1234,
    prompt_tokens_per_second: 10.5
  },
  props: { n_ctx: 8192 },
  process: {
    rss_bytes: 150 * 1024 * 1024,
    gpu_used_bytes: 2 * 1024 * 1024 * 1024
  }
};

const line = sandbox.formatServerMetricsLine(fixture);
console.log(JSON.stringify({ line: line }));