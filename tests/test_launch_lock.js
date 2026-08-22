// Launch lock: the Stage names the live endpoint, and start/stop toasts speak
// in that same language.
//
// The pure helpers are imported from the modules that ship them. The wiring
// checks below still read app.js as text, because startProfile/stopProfileByMode/
// announceServerTransitions have not moved out of it yet -- they convert when
// their panel modules land.
const fs = require('fs');
const path = require('path');

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

(async () => {
  const {
    serverEndpoint, serverUrl, launchLockCopy, launchLockHtml,
    listeningToast, releasedToast, launchControlState,
  } = await import('../lcc_api/static/js/launch.js');
  const { chatEmptyCopy } = await import('../lcc_api/static/js/copy.js');

  const live = { running: true, host: '127.0.0.1', port: 18100, pid: 4242 };
  const idle = { running: false, host: '127.0.0.1', port: 18100, pid: 4242 };
  const readyProfile = { launchable: true };
  const idleControls = launchControlState(readyProfile, idle, false);
  const liveControls = launchControlState(readyProfile, live, false);
  const waitControls = launchControlState(readyProfile, null, true);
  const lock = launchLockCopy(live);
  const html = launchLockHtml(lock);
  const chatLive = chatEmptyCopy(true, live);

  // Wiring checks against source text. A missing extraction must fail loudly:
  // an empty string would quietly satisfy none of the includes() below, but
  // naming the reason beats a bare false.
  const sliceOf = (needle, len) => {
    const at = src.indexOf(needle);
    if (at === -1) {
      console.log(JSON.stringify({ ok: false, error: `not found in app.js: ${needle}` }));
      process.exit(1);
    }
    return src.slice(at, at + len);
  };
  const startSrc = sliceOf('async function startProfile', 2200);
  const stopSrc = sliceOf('async function stopProfileByMode', 900);
  const crashSrc = sliceOf('function announceServerTransitions', 900);
  const waitingSrc = extractFunctionSource('setLaunchWaiting');
  if (!waitingSrc) {
    console.log(JSON.stringify({ ok: false, error: 'setLaunchWaiting not found in app.js' }));
    process.exit(1);
  }

  const ok = (
    serverEndpoint(live) === '127.0.0.1:18100'
    && serverUrl(live) === 'http://127.0.0.1:18100'
    && launchLockCopy(idle) === null
    && launchLockCopy(null) === null
    && lock.status === 'Listening'
    && lock.endpoint === '127.0.0.1:18100'
    && lock.detail === 'PID 4242'
    && /Listening/.test(html)
    && /127\.0\.0\.1:18100/.test(html)
    && /data-launch-action="copy"/.test(html)
    && /data-launch-action="chat"/.test(html)
    && listeningToast(live, 'Qwen') === 'Listening on 127.0.0.1:18100'
    && releasedToast(live, 'Qwen') === 'Released 127.0.0.1:18100'
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
    && /Waiting to listen/.test(waitingSrc)
    && stopSrc.includes('releasedToast')
    && /Open logs/.test(crashSrc)
  );

  console.log(JSON.stringify({
    ok,
    endpoint: serverEndpoint(live),
    toast: listeningToast(live, 'Qwen'),
    released: releasedToast(live, 'Qwen'),
    lock,
    chatNamesPort: /18100/.test(chatLive.body || ''),
    startWired: startSrc.includes('listeningToast'),
    stopWired: stopSrc.includes('releasedToast'),
  }));
  process.exit(ok ? 0 : 1);
})();
