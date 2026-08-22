// Shared application state. The binding is read-only across a module
// boundary; its properties are not -- mutate state.foo, never reassign state.

// Module scope must stay importable outside a browser: the node tests import
// this file, and there is no localStorage there. Reads fall back to the same
// defaults the app uses on a first visit.
const stored = (key) => {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage.getItem(key);
  } catch {
    return null;
  }
};

export const state = {
  inventory: null,
  config: null,
  hardware: null,
  profiles: [],
  servers: [],
  meta: null,
  runtimeUpdates: null,
  selectedProfileMode: null,
  selectedServerId: null,
  paramOverrides: {},
  lastEstimateKey: '',
  lastBenchmarkKey: '',
  measuredTps: null,
  measuredElapsed: null,
  paramPreviewHost: '127.0.0.1',
  paramPreviewPort: 8080,
  modelNotes: { hf: '', fit: '', benchmark: '' },
  profileFilter: 'all',
  profileModelFilter: 'all',
  hideUnavailableProfiles: stored('lcc-hide-unavailable-profiles') === '1',
  hideNotInstalledRuntimes: stored('lcc-hide-not-installed-runtimes') === '1',
  showAllRuntimes: false,
  query: '',
  chatHistory: {},  // { [mode]: Array<{role: 'user'|'assistant', content: string}> }
  jinjaRecommended: false,
  // Three-state: 'light', 'dark', or 'system'. 'system' is the default until
  // someone picks a side, so the app opens in dark on a dark desktop instead
  // of flashing the light palette — and it stays a state you can return to.
  theme: stored('lcc-theme') || 'system',
};
