// The whole module graph must evaluate without throwing.
//
// This exists because the frontend module split shipped an app that loaded
// nothing: wireEvents() was partitioned by selector, which separated
// `const palBack = $('#command-palette')` from the `if (palBack) ...` that
// used it. Every other check passed -- the files parsed, every module
// imported, every line of the original wiring still existed, every init was
// called, and all 258 tests were green -- because none of them ever ran the
// app's own boot sequence. A ReferenceError at boot kills every listener on
// the page, so the dashboard rendered and did absolutely nothing.
//
// The DOM here is a stub. It is not a fake browser and proves nothing about
// behaviour; it only answers "does importing app.js throw".
const path = require('path');
const { pathToFileURL } = require('url');

const noop = () => {};
let el;
el = new Proxy({}, {
  get(_, k) {
    if (k === 'classList') return { toggle: noop, add: noop, remove: noop, contains: () => false };
    if (k === 'dataset') return {};
    if (k === 'style') return {};
    if (k === 'value' || k === 'textContent' || k === 'innerHTML' || k === 'title') return '';
    if (k === 'checked' || k === 'hidden' || k === 'disabled') return false;
    if (k === 'children' || k === 'options' || k === 'files') return [];
    if (k === 'querySelectorAll') return () => [];
    if (k === 'querySelector' || k === 'closest') return () => el;
    if (k === 'parentElement' || k === 'firstElementChild' || k === 'nextElementSibling') return el;
    if (k === 'getBoundingClientRect') return () => ({ top: 0, left: 0, width: 0, height: 0, bottom: 0, right: 0 });
    if (k === 'getAttribute') return () => null;
    if (k === 'scrollHeight' || k === 'scrollTop' || k === 'clientHeight' || k === 'offsetHeight') return 0;
    if (k === 'tagName') return 'DIV';
    if (typeof k === 'symbol') return undefined;
    return noop;
  },
  set() { return true; },
});

globalThis.document = {
  querySelector: () => el,
  querySelectorAll: () => [],
  getElementById: () => el,
  createElement: () => el,
  addEventListener: noop,
  removeEventListener: noop,
  body: el,
  documentElement: el,
  activeElement: el,
  hidden: false,
};
// Timers are inert: the app starts poll loops at boot, and real timers would
// keep this process alive forever.
const timers = { setTimeout: () => 0, clearTimeout: noop, setInterval: () => 0, clearInterval: noop };
globalThis.window = {
  matchMedia: () => ({ matches: false, addEventListener: noop, addListener: noop }),
  addEventListener: noop,
  removeEventListener: noop,
  location: { hash: '', href: 'http://localhost:8716/' },
  requestAnimationFrame: noop,
  innerWidth: 1920,
  innerHeight: 1080,
  devicePixelRatio: 1,
  getComputedStyle: () => ({ getPropertyValue: () => '' }),
  ...timers,
};
Object.assign(globalThis, timers);
globalThis.location = globalThis.window.location;
globalThis.history = { replaceState: noop, pushState: noop };
globalThis.localStorage = {
  _d: {},
  getItem(k) { return this._d[k] ?? null; },
  setItem(k, v) { this._d[k] = String(v); },
  removeItem(k) { delete this._d[k]; },
};
globalThis.requestAnimationFrame = noop;
Object.defineProperty(globalThis, 'navigator', {
  value: { clipboard: { writeText: async () => {} } }, configurable: true,
});
globalThis.fetch = async () => ({ ok: true, json: async () => ({}), text: async () => '' });
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });

(async () => {
  const app = pathToFileURL(path.join(__dirname, '..', 'lcc_api', 'static', 'app.js')).href;
  try {
    await import(app);
  } catch (e) {
    const frame = (e.stack || '').split('\n').slice(1)
      .find((l) => l.includes('static')) || '';
    console.log(JSON.stringify({
      ok: false,
      error: `${e.constructor.name}: ${e.message}`,
      at: frame.trim(),
    }));
    process.exit(1);
  }
  console.log(JSON.stringify({ ok: true, booted: true }));
  process.exit(0);
})();
