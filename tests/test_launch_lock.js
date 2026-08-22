// Launch lock: the Stage names the live endpoint, and start/stop toasts speak
// in that same language.
//
// The pure helpers are imported. The wiring checks still read source text,
// because they assert that one function *calls* another -- which importing a
// function cannot show. They now read the panel modules that own that code.
const fs = require('fs');
const path = require('path');

const read = (rel) => fs.readFileSync(path.join(__dirname, '..', 'lcc_api/static', rel), 'utf8');
const src = read('js/panels/servers.js');
const paramsSrc = read('js/panels/parameters.js');

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
  const sliceOf = (needle, len, from = src) => {
    const at = from.indexOf(needle);
    if (at === -1) {
      console.log(JSON.stringify({ ok: false, error: `not found: ${needle}` }));
      process.exit(1);
    }
    return from.slice(at, at + len);
  };
  const startSrc = sliceOf('export async function startProfile', 2200);
  const stopSrc = sliceOf('export async function stopProfileByMode', 900);
  const crashSrc = sliceOf('export function announceServerTransitions', 900);
  const waitingSrc = sliceOf('export function setLaunchWaiting', 400, paramsSrc);

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
