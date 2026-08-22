// Smart Fit UI: notes must be visible, and a CPU-fallback pick must not
// be written into the form until the user applies it.
//
// The tune helpers are imported from tune.js. The summary checks now assert on
// *rendered output* rather than on the source text of renderTuneSummary --
// same intent, but it fails when the markup breaks instead of when the source
// happens to be reworded. runAutoTune's wiring is still read as text -- an
// import cannot show that one function calls another.
const fs = require('fs');
const path = require('path');

const fitJs = fs.readFileSync(path.join(__dirname, '..', 'lcc_api', 'static', 'js', 'panels', 'fit.js'), 'utf8');

(async () => {
  const {
    renderTuneNotes, shouldAutoApplyTune, renderTuneSummary,
  } = await import('../lcc_api/static/js/tune.js');

  const gpuOk = { success: true, cpu_fallback: false };
  const cpuHold = { success: true, cpu_fallback: true };
  const notesHtml = renderTuneNotes([
    'A process is already using this GPU. Smart Fit sized the full card.',
  ]);

  const autoGpu = shouldAutoApplyTune(gpuOk);
  const autoCpu = shouldAutoApplyTune(cpuHold);
  const autoFail = shouldAutoApplyTune({ success: false });

  // Render the summary in both states rather than grepping its source.
  const result = {
    cpu_fallback: false,
    notes: ['A process is already using this GPU. Smart Fit sized the full card.'],
    changes: [{ field: 'ctx_size', from: 4096, to: 8192, why: 'more headroom' }],
    before: { fit_status: { status: 'tight' }, speed_estimate: { estimate_tps: 20 } },
    after: { fit_status: { status: 'good' }, speed_estimate: { estimate_tps: 28 } },
  };
  const proposed = renderTuneSummary(result, { applied: false });
  const applied = renderTuneSummary(result, { applied: true });
  const cpuSummary = renderTuneSummary({ ...result, cpu_fallback: true }, { applied: false });

  const summaryOk = (
    proposed.includes('Proposed changes')
    && applied.includes('Changes applied')
    && proposed.includes('tune-notes')
    && proposed.includes('already using this GPU')
    && cpuSummary.includes('data-tune-index="0"')
    && cpuSummary.includes('cannot hold')
  );

  const runAt = fitJs.indexOf('export async function runAutoTune');
  if (runAt === -1) {
    console.log(JSON.stringify({ ok: false, error: 'runAutoTune not found in panels/fit.js' }));
    process.exit(1);
  }
  const runSrc = fitJs.slice(runAt, runAt + 2000);

  const ok = (
    autoGpu === true
    && autoCpu === false
    && autoFail === false
    && /already using this GPU/.test(notesHtml)
    && summaryOk
    && runSrc.includes('shouldAutoApplyTune')
    && /cpu_fallback/.test(runSrc)
  );

  console.log(JSON.stringify({
    ok,
    autoGpu,
    autoCpu,
    autoFail,
    notesVisible: /already using this GPU/.test(notesHtml),
    summaryOk,
    runWired: runSrc.includes('shouldAutoApplyTune'),
  }));
  process.exit(ok ? 0 : 1);
})();
