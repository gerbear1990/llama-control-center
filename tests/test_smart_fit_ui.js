// Smart Fit UI: notes must be visible, and a CPU-fallback pick must not
// be written into the form until the user applies it.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const appJs = fs.readFileSync(path.join(__dirname, '..', 'lcc_api', 'static', 'app.js'), 'utf8');

function extractFunctionSource(src, name) {
  const start = src.indexOf('function ' + name);
  if (start === -1) return null;
  let i = src.indexOf('{', start);
  if (i === -1) return null;
  let depth = 1;
  i += 1;
  while (i < src.length && depth > 0) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') depth -= 1;
    i += 1;
  }
  return depth === 0 ? src.substring(start, i) : null;
}

const needed = ['escapeHtml', 'renderTuneNotes', 'shouldAutoApplyTune'];
const missing = needed.filter((name) => !extractFunctionSource(appJs, name));
if (missing.length) {
  console.log(JSON.stringify({ ok: false, error: 'missing ' + missing.join(', ') }));
  process.exit(1);
}

const ctx = {};
vm.createContext(ctx);
vm.runInContext(
  needed.map((name) => extractFunctionSource(appJs, name)).join('\n')
    + '; this.shouldAutoApplyTune = shouldAutoApplyTune;'
    + ' this.renderTuneNotes = renderTuneNotes;',
  ctx,
);

const gpuOk = { success: true, cpu_fallback: false };
const cpuHold = { success: true, cpu_fallback: true };
const notesHtml = ctx.renderTuneNotes([
  'A process is already using this GPU. Smart Fit sized the full card.',
]);
const summaryAt = appJs.indexOf('function renderTuneSummary');
const summarySrc = summaryAt === -1 ? '' : appJs.slice(summaryAt, summaryAt + 3500);
const runAt = appJs.indexOf('async function runAutoTune');
const runSrc = runAt === -1 ? '' : appJs.slice(runAt, runAt + 2000);

const autoGpu = ctx.shouldAutoApplyTune(gpuOk);
const autoCpu = ctx.shouldAutoApplyTune(cpuHold);
const autoFail = ctx.shouldAutoApplyTune({ success: false });

const ok = (
  autoGpu === true
  && autoCpu === false
  && autoFail === false
  && /already using this GPU/.test(notesHtml)
  && summarySrc.includes('renderTuneNotes')
  && summarySrc.includes('Proposed changes')
  && summarySrc.includes('Changes applied')
  && summarySrc.includes('data-tune-index="0"')
  && summarySrc.includes('cannot hold')
  && runSrc.includes('shouldAutoApplyTune')
  && /cpu_fallback/.test(runSrc)
);

console.log(JSON.stringify({
  ok,
  autoGpu,
  autoCpu,
  autoFail,
  notesVisible: /already using this GPU/.test(notesHtml),
  summaryWired: summarySrc.includes('renderTuneNotes'),
  runWired: runSrc.includes('shouldAutoApplyTune'),
}));
process.exit(ok ? 0 : 1);
