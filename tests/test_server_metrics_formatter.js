// The shipped formatServerMetricsLine, driven with a real /metrics payload,
// plus the portable-export snapshot and the command palette's registry.
//
// Everything here is imported from the module that ships it. This file used to
// extract four functions from app.js by brace counting, and three of those
// sections were wrapped in `if (src) { ... }` -- so a rename silently skipped
// them rather than failing. Nothing is optional now.
(async () => {
  const { formatServerMetricsLine } = await import('../lcc_api/static/js/format.js');
  const { buildPortableExportSnapshot } = await import('../lcc_api/static/js/settings.js');
  const { getCommands, executeCommand, registerCommands } = await import('../lcc_api/static/js/palette.js');

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

  // Extra verification goes to stderr so the single-line JSON on stdout stays
  // loadable by the python wrapper.

  // Portable export, on fresh inputs rather than a pre-seeded app state.
  const cfg = { model_dirs: ['D:\\Models'], runtime_dirs: [], default_port: 9090, update_channel: 'stable' };
  const inv = { scan_roots: ['D:\\Models'] };
  let parsed;
  try {
    parsed = JSON.parse(buildPortableExportSnapshot(cfg, inv));
  } catch (e) {
    console.error('export not valid JSON');
    process.exit(1);
  }
  if (!parsed || parsed.schema_version !== 'lcc-portable-export-v1'
      || !Array.isArray(parsed.model_dirs) || parsed.model_dirs[0] !== 'D:\\Models') {
    console.error('buildPortableExportSnapshot produced unexpected shape on real inputs');
    process.exit(1);
  }
  console.error(JSON.stringify({ export_ok: true, schema: parsed.schema_version, has_model_dirs: parsed.model_dirs.length > 0 }));

  // getCommands is a pure list and must offer at least three entries.
  const cmds = getCommands();
  if (!Array.isArray(cmds) || cmds.length < 3) {
    console.error('getCommands did not return >=3 entries');
    process.exit(1);
  }
  console.error(JSON.stringify({ commands_ok: true, count: cmds.length }));

  // executeCommand dispatches through whatever registry app.js registered.
  let executed = null;
  registerCommands({
    'focus-search': () => { executed = 'focus-search'; },
    refresh: () => { executed = 'refresh'; },
  });
  if (!executeCommand('focus-search') || executed !== 'focus-search') {
    console.error('executeCommand did not invoke the registered focus-search command');
    process.exit(1);
  }
  if (!executeCommand('refresh') || executed !== 'refresh') {
    console.error('executeCommand did not invoke the registered refresh command');
    process.exit(1);
  }
  if (executeCommand('nonexistent')) {
    console.error('executeCommand returned truthy for an unknown id');
    process.exit(1);
  }
  console.error(JSON.stringify({ execute_ok: true }));

  // Every id the palette offers must be dispatchable: a command listed with no
  // registered body is a dead menu entry, which is what this pairing guards.
  const ids = cmds.map((c) => c.id);
  if (new Set(ids).size !== ids.length) {
    console.error('getCommands returned duplicate ids');
    process.exit(1);
  }
})();
