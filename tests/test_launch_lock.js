// Launch lock: the Stage names the live endpoint, and start/stop
// toasts speak in that same language. Pure helpers, no DOM.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'lcc_api/static/app.js'), 'utf8');

function extractFunctionSource(name) {
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

const needed = [
  'escapeHtml',
  'serverEndpoint',
  'serverUrl',
  'launchLockCopy',
  'launchLockHtml',
  'listeningToast',
  'releasedToast',
  'launchControlState',
  'chatEmptyCopy',
];
const missing = needed.filter((name) => !extractFunctionSource(name));
if (missing.length) {
  console.log(JSON.stringify({ ok: false, error: 'missing ' + missing.join(', ') }));
  process.exit(1);
}

const ctx = {};
vm.createContext(ctx);
vm.runInContext(
  needed.map((name) => extractFunctionSource(name)).join('\n')
    + '; this.serverEndpoint = serverEndpoint;'
    + ' this.serverUrl = serverUrl;'
    + ' this.launchLockCopy = launchLockCopy;'
    + ' this.launchLockHtml = launchLockHtml;'
    + ' this.listeningToast = listeningToast;'
    + ' this.releasedToast = releasedToast;'
    + ' this.launchControlState = launchControlState;'
    + ' this.chatEmptyCopy = chatEmptyCopy;',
  ctx,
);

const live = { running: true, host: '127.0.0.1', port: 18100, pid: 4242 };
const idle = { running: false, host: '127.0.0.1', port: 18100, pid: 4242 };
const readyProfile = { launchable: true };
const idleControls = ctx.launchControlState(readyProfile, idle, false);
const liveControls = ctx.launchControlState(readyProfile, live, false);
const waitControls = ctx.launchControlState(readyProfile, null, true);
const lock = ctx.launchLockCopy(live);
const html = ctx.launchLockHtml(lock);
const chatLive = ctx.chatEmptyCopy(true, live);

const startSrc = (() => {
  const at = src.indexOf('async function startProfile');
  return at === -1 ? '' : src.slice(at, at + 2200);
})();
const stopSrc = (() => {
  const at = src.indexOf('async function stopProfileByMode');
  return at === -1 ? '' : src.slice(at, at + 900);
})();
const crashSrc = (() => {
  const at = src.indexOf('function announceServerTransitions');
  return at === -1 ? '' : src.slice(at, at + 900);
})();

const ok = (
  ctx.serverEndpoint(live) === '127.0.0.1:18100'
  && ctx.serverUrl(live) === 'http://127.0.0.1:18100'
  && ctx.launchLockCopy(idle) === null
  && ctx.launchLockCopy(null) === null
  && lock.status === 'Listening'
  && lock.endpoint === '127.0.0.1:18100'
  && lock.detail === 'PID 4242'
  && /Listening/.test(html)
  && /127\.0\.0\.1:18100/.test(html)
  && /data-launch-action="copy"/.test(html)
  && /data-launch-action="chat"/.test(html)
  && ctx.listeningToast(live, 'Qwen') === 'Listening on 127.0.0.1:18100'
  && ctx.releasedToast(live, 'Qwen') === 'Released 127.0.0.1:18100'
  && idleControls.startDisabled === false
  && idleControls.stopDisabled === true
  && liveControls.startDisabled === true
  && liveControls.stopDisabled === false
  && /18100/.test(liveControls.startTitle)
  && waitControls.startDisabled === true
  && /18100/.test(chatLive.body)
  && startSrc.includes('listeningToast')
  && startSrc.includes('justLocked')
  && startSrc.includes('setLaunchWaiting')
  && startSrc.includes('Start server')
  && /Waiting to listen/.test(extractFunctionSource('setLaunchWaiting') || '')
  && stopSrc.includes('releasedToast')
  && /Open logs/.test(crashSrc)
);

console.log(JSON.stringify({
  ok,
  endpoint: ctx.serverEndpoint(live),
  toast: ctx.listeningToast(live, 'Qwen'),
  released: ctx.releasedToast(live, 'Qwen'),
  lock,
  chatNamesPort: /18100/.test(chatLive.body || ''),
  startWired: startSrc.includes('listeningToast'),
  stopWired: stopSrc.includes('releasedToast'),
}));
process.exit(ok ? 0 : 1);
