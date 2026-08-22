// The shipped formatServerMetricsLine, driven with a real /metrics payload.
//
// formatServerMetricsLine is imported from format.js. buildPortableExportSnapshot,
// getCommands and executeCommand still live in app.js and are still extracted as
// text -- they convert when settings.js and palette.js land.
//
// Those three sections used to be skipped silently when extraction failed
// (`if (gcSrc) { ... }`), which meant a rename would have quietly un-covered
// them. They are mandatory now.
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const appJs = path.join(__dirname, '../lcc_api/static/app.js');
const fullCode = fs.readFileSync(appJs, 'utf8');

// Robust extraction of a function source from the real shipped file by brace
// counting. Avoids running any top-level init code.
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

function requireSource(name) {
  const src = extractFunctionSource(fullCode, name);
  if (!src) {
    console.error(`Could not extract ${name} from shipped app.js`);
    process.exit(1);
  }
  return src;
}

(async () => {
  const { formatServerMetricsLine } = await import('../lcc_api/static/js/format.js');

  // Fixture taken from the real /metrics success shape (summary + props + process).
  const fixture = {
    summary: {
      kv_cache_usage_ratio: 0.42,
      predicted_tokens_per_second: 3.2,
      slots_active: 1,
      slots_processing: 1,
      kv_cache_tokens: 1234,
      prompt_tokens_per_second: 10.5,
    },
    props: { n_ctx: 8192 },
    process: {
      rss_bytes: 150 * 1024 * 1024,
      gpu_used_bytes: 2 * 1024 * 1024 * 1024,
    },
  };

  const line = formatServerMetricsLine(fixture);
  console.log(JSON.stringify({ line: line }));

  // --- Still-in-app.js helpers, extracted and run in a sandbox ---
  // Extra verification goes to stderr so the single-line JSON on stdout stays
  // loadable by the python wrapper.
  const sandbox = { console: console };
  vm.createContext(sandbox);

  vm.runInContext(requireSource('buildPortableExportSnapshot'), sandbox);
  if (typeof sandbox.buildPortableExportSnapshot !== 'function') {
    console.error('buildPortableExportSnapshot not callable after vm eval of shipped source');
    process.exit(1);
  }

  // Fresh state-like inputs (no pre-seeded full app state)
  const cfg = { model_dirs: ['D:\\Models'], runtime_dirs: [], default_port: 9090, update_channel: 'stable' };
  const inv = { scan_roots: ['D:\\Models'] };
  const exported = sandbox.buildPortableExportSnapshot(cfg, inv);
  let parsed;
  try {
    parsed = JSON.parse(exported);
  } catch (e) {
    console.error('export not valid JSON');
    process.exit(1);
  }
  if (!parsed || parsed.schema_version !== 'lcc-portable-export-v1'
      || !Array.isArray(parsed.model_dirs) || parsed.model_dirs[0] !== 'D:\\Models') {
    console.error('shipped buildPortableExportSnapshot produced unexpected shape on real inputs');
    process.exit(1);
  }
  console.error(JSON.stringify({ export_ok: true, schema: parsed.schema_version, has_model_dirs: parsed.model_dirs.length > 0 }));

  // getCommands: a pure list, must offer at least three entries.
  vm.runInContext(requireSource('getCommands'), sandbox);
  const cmds = (typeof sandbox.getCommands === 'function') ? sandbox.getCommands() : [];
  if (!Array.isArray(cmds) || cmds.length < 3) {
    console.error('getCommands from shipped did not return >=3 entries');
    process.exit(1);
  }
  console.error(JSON.stringify({ commands_ok: true, count: cmds.length }));

  // Drive the shipped executeCommand path with a fresh stub registry.
  vm.runInContext(requireSource('executeCommand'), sandbox);
  sandbox.COMMAND_REGISTRY = {
    'focus-search': function () { sandbox.__executed = 'focus-search'; },
    refresh: function () { sandbox.__executed = 'refresh'; },
  };
  const didFocus = sandbox.executeCommand('focus-search');
  if (!didFocus || sandbox.__executed !== 'focus-search') {
    console.error('executeCommand did not invoke shipped stub for focus-search');
    process.exit(1);
  }
  const didRefresh = sandbox.executeCommand('refresh');
  if (!didRefresh || sandbox.__executed !== 'refresh') {
    console.error('executeCommand did not invoke shipped stub for refresh');
    process.exit(1);
  }
  const didUnknown = sandbox.executeCommand('nonexistent');
  if (didUnknown) {
    console.error('executeCommand returned truthy for unknown id');
    process.exit(1);
  }
  console.error(JSON.stringify({ execute_ok: true }));
})();
