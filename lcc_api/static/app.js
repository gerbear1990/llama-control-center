const state = {
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
  hideUnavailableProfiles: localStorage.getItem('lcc-hide-unavailable-profiles') === '1',
  hideNotInstalledRuntimes: localStorage.getItem('lcc-hide-not-installed-runtimes') === '1',
  showAllRuntimes: false,
  query: '',
  chatHistory: {},  // { [mode]: Array<{role: 'user'|'assistant', content: string}> }
  jinjaRecommended: false,
  // Three-state: 'light', 'dark', or 'system'. 'system' is the default until
  // someone picks a side, so the app opens in dark on a dark desktop instead
  // of flashing the light palette — and it stays a state you can return to.
  theme: localStorage.getItem('lcc-theme') || 'system',
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object || {}, key);
const PARAM_DEFAULTS = {
  runtime: 'llama.cpp',
  host: '127.0.0.1',
  port: 8080,
  acceleration_backend: 'auto',
  device: 'auto',
  ctx_size: 4096,
  threads: 4,
  threads_batch: 4,
  batch_size: 512,
  ubatch_size: 512,
  gpu_layers: 999,
  fit_target_mib: 1024,
  fit_headroom_mib: '',
  cache_type_k: 'q4_0',
  cache_type_v: 'q4_0',
  temperature: 0.8,
  n_predict: -1,
  top_k: 40,
  top_p: 0.95,
  min_p: 0.05,
  repeat_last_n: 64,
  repeat_penalty: 1,
  presence_penalty: 0,
  frequency_penalty: 0,
  seed: -1,
  draft_model: '',
  flash_attn: true,
  reasoning: false,
  kv_offload: true,
  op_offload: true,
  jinja: false,
  mmap: true,
};
const FIT_APPLIED_FIELDS = [
  ['ctx_size', '#param-ctx'],
  ['acceleration_backend', '#param-acceleration'],
  ['device', '#param-device'],
  ['threads', '#param-threads'],
  ['threads_batch', '#param-threads-batch'],
  ['batch_size', '#param-batch'],
  ['ubatch_size', '#param-ubatch'],
  ['gpu_layers', '#param-gpu-layers'],
  ['fit_target_mib', '#param-fit-target'],
  ['fit_headroom_mib', '#param-fit-headroom'],
  ['cache_type_k', '#param-cache-k'],
  ['cache_type_v', '#param-cache-v'],
  ['temperature', '#param-temperature'],
  ['n_predict', '#param-predict'],
  ['top_k', '#param-top-k'],
  ['top_p', '#param-top-p'],
  ['min_p', '#param-min-p'],
  ['repeat_last_n', '#param-repeat-last-n'],
  ['repeat_penalty', '#param-repeat-penalty'],
  ['presence_penalty', '#param-presence-penalty'],
  ['frequency_penalty', '#param-frequency-penalty'],
  ['seed', '#param-seed'],
  ['kv_offload', '#param-kv-offload'],
  ['op_offload', '#param-op-offload'],
  ['jinja', '#param-jinja'],
];

function formatBytes(bytes) {
  if (!bytes) return '-';
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  const mb = bytes / 1024 ** 2;
  return `${mb.toFixed(0)} MB`;
}

function formatMib(mib) {
  if (mib === undefined || mib === null || Number.isNaN(Number(mib))) return '-';
  const value = Number(mib);
  if (Math.abs(value) >= 1024) return `${(value / 1024).toFixed(1)} GB`;
  return `${Math.round(value)} MiB`;
}

// Compact relative-time formatter for the profile Updated column. Unix
function fitStatusClass(status) {
  if (status === 'good') return 'ok';
  if (status === 'tight') return 'warn';
  if (status === 'near_limit') return 'error';
  return '';
}

function fitStatusLabel(status) {
  return {
    good: 'Good',
    tight: 'Tight',
    near_limit: 'Near Limit',
    unknown: 'Unknown',
  }[status] || 'Unknown';
}

function listToLines(values) {
  return (values || []).filter(Boolean).join('\n');
}

function linesToList(value) {
  return String(value || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

// Toasts are short text snippets shown in the bottom-right. They may carry
// a single optional action button (e.g. 'Use port 18100') that the user can
// click while the toast is still visible. ``toast.action(message, action)`` is
// the recommended form; ``toast(message)`` keeps the simple text-only path
// so existing call sites are unchanged.
function toast(message, action) {
  const el = $('#toast');
  el.innerHTML = '';
  const text = document.createElement('span');
  text.textContent = message;
  el.appendChild(text);
  const persist = Boolean(action && action.label && typeof action.onClick === 'function');
  if (persist) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'toast-action';
    button.textContent = action.label;
    button.addEventListener('click', () => {
      window.clearTimeout(toast.timer);
      el.classList.remove('show');
      action.onClick();
    });
    el.appendChild(button);
    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'toast-action';
    dismiss.setAttribute('aria-label', 'Dismiss');
    dismiss.textContent = 'Dismiss';
    dismiss.addEventListener('click', () => {
      window.clearTimeout(toast.timer);
      el.classList.remove('show');
    });
    el.appendChild(dismiss);
  }
  el.classList.add('show');
  window.clearTimeout(toast.timer);
  toast.timer = persist ? null : window.setTimeout(() => el.classList.remove('show'), 5000);
}

// Live port-availability indicator next to the Port field. Probes
// /api/system/check-port on every edit (debounced 350ms) and renders a
// green dot when the port is free, a red dot when something else is
// bound there, and a grey dot while the probe is in flight.
let portCheckTimer = null;
let portCheckSeq = 0;

// The dot is a real control (role="button", Enter/Space re-probes), so the
// state it carries has to reach assistive tech too: title and aria-label are
// written together and never drift apart.
function setPortStatus(stateClass, text) {
  const statusEl = $('#param-port-status');
  if (!statusEl) return;
  statusEl.className = `port-status ${stateClass}`;
  statusEl.title = `${text} — click to check again`;
  statusEl.setAttribute('aria-label', `${text}. Check port again.`);
}

async function checkPortNow(port, host) {
  const seq = ++portCheckSeq;
  const statusEl = $('#param-port-status');
  if (!statusEl) return;
  setPortStatus('checking', `Checking port ${port}`);
  try {
    const qs = `port=${encodeURIComponent(port)}&host=${encodeURIComponent(host || '127.0.0.1')}`;
    const data = await api(`/api/system/check-port?${qs}`);
    if (seq !== portCheckSeq) return; // a newer probe has superseded us
    if (data.free) {
      setPortStatus('free', `Port ${data.port} is free`);
    } else if (data.port_in_use_reason === 'reserved') {
      // The OS denies bind on this port even though nothing is listening.
      // That's the failure mode Windows machines hit when the default
      // dynamic port range (1024-15200) covers a profile's default port.
      const rng = data.reserved_range || {};
      setPortStatus('busy', `Port ${data.port} is inside the Windows reserved range ${rng.start ?? '?'}-${rng.end ?? '?'}. Pick a port above ${rng.end ?? '?'}. Suggested free port: ${data.suggested_port ?? 'none'}`);
    } else {
      const holder = data.port_holder;
      const who = holder?.process_name && holder?.pid
        ? `${holder.process_name} (PID ${holder.pid})`
        : holder?.process_name || holder?.pid || 'another process';
      setPortStatus('busy', `Port ${data.port} is in use by ${who}. Suggested free port: ${data.suggested_port ?? 'none'}`);
    }
  } catch {
    setPortStatus('unknown', 'Could not check the port');
  }
}

function schedulePortCheck() {
  window.clearTimeout(portCheckTimer);
  portCheckTimer = window.setTimeout(() => {
    const portInput = $('#param-port');
    const port = numericValue(portInput);
    if (!port) return;
    const host = $('#param-host')?.value.trim() || '127.0.0.1';
    checkPortNow(port, host);
  }, 350);
}

// The busy state hides the label behind a spinner, so the visual change has to
// be mirrored with aria-busy — otherwise a screen reader still reads the button
// as idle while the request is in flight.
async function withBusy(button, fn) {
  if (!button) return fn();
  const wasDisabled = button.disabled;
  button.disabled = true;
  button.classList.add('busy');
  button.setAttribute('aria-busy', 'true');
  try {
    return await fn();
  } finally {
    button.disabled = wasDisabled;
    button.classList.remove('busy');
    button.removeAttribute('aria-busy');
  }
}

function setActionsBusy(mode, busy) {
  $$(`button[data-mode="${CSS.escape(mode || '')}"]`).forEach((button) => {
    if (busy) {
      button.disabled = true;
      button.classList.add('busy');
      button.setAttribute('aria-busy', 'true');
    } else {
      button.disabled = false;
      button.classList.remove('busy');
      button.removeAttribute('aria-busy');
    }
  });
}

function confirmAction({ title = 'Confirm', message = '', confirmLabel = 'Confirm', cancelLabel = 'Cancel', confirmKind = 'primary' } = {}) {
  const modal = $('#confirm-modal');
  const titleEl = $('#confirm-title');
  const messageEl = $('#confirm-message');
  const okButton = $('#confirm-ok');
  const cancelButton = $('#confirm-cancel');
  titleEl.textContent = title;
  messageEl.textContent = message;
  okButton.textContent = confirmLabel;
  cancelButton.textContent = cancelLabel;
  okButton.classList.remove('primary', 'danger');
  if (confirmKind === 'danger') okButton.classList.add('danger');
  else okButton.classList.add('primary');
  modal.hidden = false;
  okButton.disabled = false;
  cancelButton.disabled = false;
  document.body.classList.add('modal-open');
  const priorFocus = document.activeElement;
  // A destructive action has to be aimed at: land on Cancel so a stray Enter
  // dismisses instead of deleting. Safe confirms still open on OK.
  const isDanger = confirmKind === 'danger';
  (isDanger ? cancelButton : okButton).focus();
  return new Promise((resolve) => {
    function cleanup() {
      modal.hidden = true;
      document.body.classList.remove('modal-open');
      okButton.removeEventListener('click', onOk);
      cancelButton.removeEventListener('click', onCancel);
      modal.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      if (priorFocus && typeof priorFocus.focus === 'function') {
        priorFocus.focus();
      }
    }
    function onOk() { cleanup(); resolve(true); }
    function onCancel() { cleanup(); resolve(false); }
    function onBackdrop(event) { if (event.target === modal) onCancel(); }
    function onKey(event) {
      if (event.key === 'Escape') {
        onCancel();
      } else if (event.key === 'Enter') {
        // Enter fires the button that actually has focus. No blanket-OK:
        // confirming a delete must be a deliberate landing on Delete.
        const active = document.activeElement;
        if (active === cancelButton) {
          event.preventDefault();
          onCancel();
        } else if (active === okButton) {
          event.preventDefault();
          onOk();
        }
      } else {
        trapTab(event, $('.confirm-dialog'));
      }
    }
    okButton.addEventListener('click', onOk);
    cancelButton.addEventListener('click', onCancel);
    modal.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);
  });
}

// Drives the name/description modal shared by "Save profile" and the row
// menu's "Save as copy". Resolves with {name, description} on OK and null on
// Cancel / Escape / backdrop click. Every listener is transient and removed in
// cleanup(), and focus returns to whatever opened the modal.
function promptProfileDetails({ title = 'Save parameters', okLabel = 'Save', name = '', description = '', message = '' } = {}) {
  const modal = $('#save-profile-modal');
  const titleEl = $('#save-profile-title');
  const noteEl = $('#save-profile-note');
  const nameInput = $('#save-profile-name');
  const descInput = $('#save-profile-desc');
  const okButton = $('#save-profile-ok');
  const cancelButton = $('#save-profile-cancel');
  if (!modal || !nameInput || !descInput || !okButton || !cancelButton) return Promise.resolve(null);
  if (titleEl) titleEl.textContent = title;
  if (noteEl) {
    noteEl.textContent = message;
    noteEl.hidden = !message;
  }
  okButton.textContent = okLabel;
  nameInput.value = name;
  descInput.value = description;
  modal.hidden = false;
  document.body.classList.add('modal-open');
  const priorFocus = document.activeElement;
  nameInput.focus();
  nameInput.select();
  return new Promise((resolve) => {
    function cleanup() {
      modal.hidden = true;
      document.body.classList.remove('modal-open');
      okButton.removeEventListener('click', onOk);
      cancelButton.removeEventListener('click', onCancel);
      modal.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      if (priorFocus && typeof priorFocus.focus === 'function') {
        priorFocus.focus();
      }
    }
    function onOk() {
      const value = nameInput.value.trim();
      // An empty name would save an unlabelled profile; keep the modal open.
      if (!value) {
        nameInput.focus();
        return;
      }
      cleanup();
      resolve({ name: value, description: descInput.value.trim() });
    }
    function onCancel() { cleanup(); resolve(null); }
    function onBackdrop(event) { if (event.target === modal) onCancel(); }
    function onKey(event) {
      if (event.key === 'Escape') onCancel();
      else if (event.key === 'Enter') { event.preventDefault(); onOk(); }
      else trapTab(event, modal.querySelector('.rename-dialog'));
    }
    okButton.addEventListener('click', onOk);
    cancelButton.addEventListener('click', onCancel);
    modal.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);
  });
}

function floatingTooltip() {
  let el = $('#floating-tooltip');
  if (!el) {
    el = document.createElement('div');
    el.id = 'floating-tooltip';
    el.className = 'floating-tooltip';
    el.hidden = true;
    document.body.appendChild(el);
  }
  return el;
}

function showFloatingTooltip(trigger) {
  const text = trigger.dataset.tooltip;
  if (!text) return;
  const tooltip = floatingTooltip();
  tooltip.textContent = text;
  tooltip.hidden = false;
  tooltip.classList.remove('visible');
  tooltip.style.left = '0px';
  tooltip.style.top = '-9999px';

  window.requestAnimationFrame(() => {
    const triggerRect = trigger.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const margin = 12;
    let left = triggerRect.left + (triggerRect.width / 2) - (tooltipRect.width / 2);
    left = Math.max(margin, Math.min(left, window.innerWidth - tooltipRect.width - margin));

    let top = triggerRect.top - tooltipRect.height - 9;
    if (top < margin) {
      top = triggerRect.bottom + 9;
    }
    top = Math.max(margin, Math.min(top, window.innerHeight - tooltipRect.height - margin));

    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
    tooltip.classList.add('visible');
  });
}

function hideFloatingTooltip() {
  const tooltip = $('#floating-tooltip');
  if (!tooltip) return;
  tooltip.classList.remove('visible');
  window.clearTimeout(hideFloatingTooltip.timer);
  hideFloatingTooltip.timer = window.setTimeout(() => {
    tooltip.hidden = true;
  }, 130);
}

function bindHelpDot(help) {
  if (help.dataset.tooltipBound === 'true') return;
  help.dataset.tooltipBound = 'true';
  help.addEventListener('mouseenter', () => showFloatingTooltip(help));
  help.addEventListener('focus', () => showFloatingTooltip(help));
  help.addEventListener('mousedown', (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  help.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    help.focus({ preventScroll: true });
    showFloatingTooltip(help);
  });
  help.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    event.stopPropagation();
    showFloatingTooltip(help);
  });
  help.addEventListener('mouseleave', hideFloatingTooltip);
  help.addEventListener('blur', hideFloatingTooltip);
}

// Theme is a three-state cycle: light -> dark -> system. Only the resolved
// value is ever stamped on the root, so the stylesheet stays two-state.
const THEME_CYCLE = ['light', 'dark', 'system'];
const THEME_LABELS = { light: 'Light', dark: 'Dark', system: 'System' };
const darkMediaQuery = window.matchMedia('(prefers-color-scheme: dark)');

function resolvedTheme() {
  if (state.theme === 'system') return darkMediaQuery.matches ? 'dark' : 'light';
  return state.theme === 'dark' ? 'dark' : 'light';
}

function applyTheme() {
  const mode = THEME_LABELS[state.theme] ? state.theme : 'system';
  const resolved = resolvedTheme();
  document.documentElement.dataset.theme = resolved;
  const button = $('#theme-button');
  if (!button) return;
  const next = THEME_CYCLE[(THEME_CYCLE.indexOf(mode) + 1) % THEME_CYCLE.length];
  const description = mode === 'system'
    ? `Theme: system (following this device, currently ${resolved})`
    : `Theme: ${mode}`;
  button.dataset.themeMode = mode;
  button.innerHTML = `<span class="theme-glyph" aria-hidden="true"></span>${escapeHtml(THEME_LABELS[mode])}`;
  button.setAttribute('title', `${description}. Switch to ${next}.`);
  button.setAttribute('aria-label', `${description}. Switch to ${next}.`);
}

function cycleTheme() {
  const mode = THEME_LABELS[state.theme] ? state.theme : 'system';
  state.theme = THEME_CYCLE[(THEME_CYCLE.indexOf(mode) + 1) % THEME_CYCLE.length];
  try {
    localStorage.setItem('lcc-theme', state.theme);
  } catch { /* private mode: the choice just lasts for this session */ }
  applyTheme();
}

function enhanceTooltips() {
  $$([
    '#param-form .field[title]',
    '#param-form .check-row label[title]',
    '#param-form .estimate-card[title]',
    '#settings-form .field[title]',
  ].join(',')).forEach((el) => {
    const text = el.getAttribute('title');
    if (!text || el.dataset.tooltipEnhanced === 'true') return;
    el.dataset.tooltipEnhanced = 'true';
    el.removeAttribute('title');
    const target = (el.classList.contains('field') || el.classList.contains('estimate-card'))
      ? el.querySelector('span')
      : el;
    if (!target) return;
    const help = document.createElement('span');
    help.className = 'help-dot';
    help.dataset.tooltip = text;
    help.tabIndex = 0;
    help.setAttribute('role', 'button');
    help.setAttribute('aria-label', text);
    help.innerHTML = '<svg viewBox="0 0 16 16" width="10" height="10" aria-hidden="true" focusable="false"><circle cx="8" cy="3.6" r="1.6" fill="currentColor"/><rect x="6.6" y="6.2" width="2.8" height="6.8" rx="0.6" fill="currentColor"/></svg>';
    target.appendChild(help);
    bindHelpDot(help);
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail || data.error || response.statusText;
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    // Preserve the original structured detail (FastAPI wraps non-2xx bodies
    // as {detail: ...}; keep it accessible so callers can branch on richer
    // fields like ``port_in_use`` or ``suggested_port``).
    err.detail = detail;
    err.status = response.status;
    throw err;
  }
  return data;
}

function setApiStatus(ok, text, details) {
  const dot = $('#api-dot');
  const status = $('#api-status');
  const copyBtn = $('#api-copy');
  if (dot) {
    dot.classList.toggle('ok', ok);
    dot.classList.toggle('error', !ok);
  }
  if (status) {
    status.textContent = text;
    if (details) status.title = details;
    else status.removeAttribute('title');
  }
  if (copyBtn) {
    copyBtn.hidden = !details;
    copyBtn.dataset.details = details || '';
  }
}

function renderVersion() {
  const el = $('#app-version');
  if (!el) return;
  el.textContent = state.meta?.version ? `v${state.meta.version}` : '';
}

async function loadDashboardResource(label, path, apply) {
  try {
    const data = await api(path);
    apply(data);
    return null;
  } catch (error) {
    return `${label}: ${error.message}`;
  }
}

function profilesEmptyCopy(total, filtering, modelCount = 0) {
  if (!total && !modelCount) {
    return {
      title: 'No profiles yet',
      body: 'Add the folders where your GGUF files live. LCC discovers them, you register a profile, then Start from Console.',
      action: 'add-folders',
      actionLabel: 'Add model folders',
    };
  }
  if (!total && modelCount) {
    return {
      title: 'Models found, no profiles',
      body: 'Register a discovered model to create a launch config. Then Start it from Console.',
      action: 'goto-models',
      actionLabel: 'Register a model',
    };
  }
  if (filtering) {
    return {
      title: 'No profiles match this filter',
      body: 'Clear the search, model filter, or “Hide unavailable” to see the full list.',
      action: 'clear-filters',
      actionLabel: 'Show all profiles',
    };
  }
  return null;
}

function modelsEmptyCopy(total, query) {
  const q = String(query || '').trim();
  if (!total) {
    return {
      title: 'No model files found',
      body: 'LCC only lists GGUF files inside your scan folders. Add a folder, then refresh.',
      action: 'add-folders',
      actionLabel: 'Add model folders',
    };
  }
  if (q) {
    return {
      title: `No models match “${q}”`,
      body: 'Try another name, or clear search to see every discovered file.',
      action: 'clear-filters',
      actionLabel: 'Clear search',
    };
  }
  return {
    title: 'No models match the current search',
    body: 'Clear search to see every discovered file.',
    action: 'clear-filters',
    actionLabel: 'Clear search',
  };
}

function runtimesEmptyCopy(total, hidingMissing) {
  if (!total) {
    return {
      title: 'No runtimes detected',
      body: 'LCC looks on PATH and in your runtime folders for llama.cpp and friends. Add a folder if the binary is not on PATH.',
      action: 'add-runtime-folders',
      actionLabel: 'Add runtime folders',
    };
  }
  if (hidingMissing) {
    return {
      title: 'No installed runtimes to show',
      body: 'Hidden because “Hide not installed” is on.',
      action: 'show-all-runtimes',
      actionLabel: 'Show all runtimes',
    };
  }
  return null;
}

function stageFirstRunCopy({ profileCount, modelCount, launchable }) {
  if (!profileCount && !modelCount) {
    return {
      title: 'Add your model folders',
      body: 'Nothing is scanned until you name a folder. Then register a profile and Start from this stage.',
      action: 'add-folders',
      actionLabel: 'Add model folders',
    };
  }
  if (!profileCount && modelCount) {
    return {
      title: 'Register a model to launch',
      body: `${modelCount} model file${modelCount === 1 ? '' : 's'} found. Register one as a profile, then Start here.`,
      action: 'goto-models',
      actionLabel: 'Register a model',
    };
  }
  if (profileCount && !launchable) {
    return {
      title: 'No launchable profiles',
      body: 'A profile is here but its model file or runtime is missing. Add folders or open Inventory to see what needs setup.',
      action: 'add-folders',
      actionLabel: 'Add model folders',
      secondaryAction: 'goto-inventory',
      secondaryLabel: 'Open Inventory',
    };
  }
  return null;
}

function serverEndpoint(server) {
  if (!server) return '';
  const host = String(server.host || '127.0.0.1').trim() || '127.0.0.1';
  const port = server.port;
  return port ? `${host}:${port}` : host;
}

function serverUrl(server) {
  const endpoint = serverEndpoint(server);
  return endpoint ? `http://${endpoint}` : '';
}

function launchLockCopy(server) {
  if (!server || !server.running) return null;
  const endpoint = serverEndpoint(server);
  if (!endpoint) return null;
  return {
    status: 'Listening',
    endpoint,
    detail: server.pid ? `PID ${server.pid}` : '',
  };
}

function launchLockHtml(copy) {
  if (!copy) return '';
  const detail = copy.detail ? `<p class="launch-lock-detail">${escapeHtml(copy.detail)}</p>` : '';
  return `
    <div class="launch-lock-main">
      <span class="badge ok">${escapeHtml(copy.status)}</span>
      <strong class="launch-lock-endpoint">${escapeHtml(copy.endpoint)}</strong>
    </div>
    ${detail}
    <div class="launch-lock-actions">
      <button type="button" class="mini-button" data-launch-action="copy">Copy URL</button>
      <button type="button" class="mini-button" data-launch-action="chat">Open Chat</button>
    </div>`;
}

function listeningToast(server, name) {
  const endpoint = serverEndpoint(server);
  return endpoint ? `Listening on ${endpoint}` : `Listening — ${name}`;
}

function releasedToast(server, name) {
  const endpoint = serverEndpoint(server);
  return endpoint ? `Released ${endpoint}` : `"${name}" stopped`;
}

function chatEmptyCopy(running, server) {
  if (!running) {
    return {
      title: 'No running server',
      body: 'Start the selected profile from the Stage. Chat talks to that server.',
      action: 'goto-stage',
      actionLabel: 'Go to Stage',
    };
  }
  const endpoint = serverEndpoint(server);
  return {
    title: 'No messages yet',
    body: endpoint
      ? `Send a prompt to ${endpoint}. Enter sends. Shift+Enter is a new line.`
      : 'Send a prompt to the running server. Enter sends. Shift+Enter is a new line.',
  };
}

function logsEmptyCopy() {
  return {
    title: 'No server selected',
    body: 'Start a profile from the Stage. Its output lands here.',
    action: 'goto-stage',
    actionLabel: 'Go to Stage',
  };
}

function serversEmptyCopy() {
  return {
    title: 'No tracked servers',
    body: 'Start a launchable profile. Tracked servers show up here so you can stop them and read logs.',
    action: 'goto-stage',
    actionLabel: 'Go to Stage',
  };
}

function emptyStateInner(copy) {
  const title = copy.title ? `<strong>${escapeHtml(copy.title)}</strong>` : '';
  const body = copy.body ? `<p>${escapeHtml(copy.body)}</p>` : '';
  const primary = ['add-folders', 'goto-models', 'goto-stage'].includes(copy.action);
  const action = copy.action
    ? `<button class="mini-button${primary ? ' primary' : ''}" type="button" data-empty-action="${escapeHtml(copy.action)}">${escapeHtml(copy.actionLabel)}</button>`
    : '';
  const secondary = copy.secondaryAction
    ? `<button class="mini-button" type="button" data-empty-action="${escapeHtml(copy.secondaryAction)}">${escapeHtml(copy.secondaryLabel)}</button>`
    : '';
  const actions = (action || secondary) ? `<div class="empty-state-actions">${action}${secondary}</div>` : '';
  return `${title}${body}${actions}`;
}

function emptyStateHtml(copy, { tableCell = false } = {}) {
  if (!copy) return '';
  const inner = `<div class="empty-state">${emptyStateInner(copy)}</div>`;
  return tableCell ? `<tr><td colspan="6">${inner}</td></tr>` : inner;
}

function renderStageFirstRun() {
  const card = $('#stage-first-run');
  const formPanel = $('#parameters');
  if (!card) return;
  const copy = stageFirstRunCopy({
    profileCount: (state.profiles || []).length,
    modelCount: (state.inventory?.models || []).length,
    launchable: (state.profiles || []).some((profile) => profile.launchable),
  });
  if (!copy) {
    card.hidden = true;
    card.innerHTML = '';
    if (formPanel) formPanel.hidden = false;
    return;
  }
  card.hidden = false;
  card.className = 'empty-state empty-state-stage';
  card.innerHTML = emptyStateInner(copy);
  if (formPanel) formPanel.hidden = !(state.profiles || []).length;
}

function showLogPreview(text, stdoutText) {
  const empty = $('#log-empty');
  const preview = $('#log-preview');
  if (empty) empty.hidden = true;
  if (preview) {
    // Only stay pinned if the reader is already at the bottom. Yanking the
    // scroll while they read back through a stack trace is how a "follow"
    // mode becomes unusable.
    const pinned = preview.scrollHeight - preview.scrollTop - preview.clientHeight < 24;
    preview.hidden = false;
    preview.textContent = text;
    if (pinned) preview.scrollTop = preview.scrollHeight;
  }
  const stdoutPane = $('#log-stdout');
  const stdoutWrap = $('#log-stream-stdout');
  if (stdoutPane && stdoutWrap) {
    const has = !!(stdoutText && stdoutText.trim());
    stdoutWrap.hidden = !has;
    if (has) {
      const pinned = stdoutPane.scrollHeight - stdoutPane.scrollTop - stdoutPane.clientHeight < 24;
      stdoutPane.textContent = stdoutText;
      if (pinned) stdoutPane.scrollTop = stdoutPane.scrollHeight;
    }
  }
}

function showLogEmpty() {
  const empty = $('#log-empty');
  const preview = $('#log-preview');
  if (empty) {
    empty.hidden = false;
    empty.className = 'empty-state';
    empty.innerHTML = emptyStateInner(logsEmptyCopy());
  }
  if (preview) preview.hidden = true;
}

function profileMatches(profile) {
  const query = state.query.trim().toLowerCase();
  if (!query) return true;
  const haystack = [
    profile.mode,
    profile.name,
    profile.description,
    profile.model?.name,
    profile.model?.path,
  ].join(' ').toLowerCase();
  return haystack.includes(query);
}

function modelMatches(model) {
  const query = state.query.trim().toLowerCase();
  if (!query) return true;
  return [model.name, model.path, model.quant, model.source].join(' ').toLowerCase().includes(query);
}

function runtimeUrl(env) {
  return env.api_url || env.details?.probe_url || '';
}

function runtimePort(env) {
  const url = runtimeUrl(env);
  if (!url) return '';
  try {
    const parsed = new URL(url);
    if (parsed.port) return parsed.port;
    return parsed.protocol === 'https:' ? '443' : '80';
  } catch {
    const match = String(url).match(/:(\d+)(?:\/|$)/);
    return match ? match[1] : '';
  }
}

function runtimeLocation(env) {
  return env.binary_path || env.details?.python_module || 'Not found on disk';
}

function renderSummary() {
  const summary = state.inventory?.summary || {};
  $('#metric-runtimes').textContent = `${summary.available_environment_count ?? 0}/${summary.environment_count ?? 0}`;
  $('#metric-launchable').textContent = state.profiles.filter((profile) => profile.launchable).length;
  $('#metric-models').textContent = summary.model_count ?? 0;
  const needsSetup = state.profiles.filter((profile) => !profile.launchable).length + (summary.legacy_portability_issue_count ?? 0);
  $('#metric-setup').textContent = needsSetup;
  const setupMetric = $('#metric-setup-wrapper');
  if (setupMetric) {
    setupMetric.setAttribute('aria-label', `${needsSetup} item${needsSetup === 1 ? '' : 's'} need setup. Show them in the profiles table.`);
  }
  const dest = $('.main')?.dataset.destination;
  if (dest === 'inventory') {
    $('#summary-line').textContent = `${state.profiles.length} profiles, ${summary.model_count ?? 0} models, ${summary.legacy_portability_issue_count ?? 0} portability issues.`;
  } else if (dest === 'console') {
    const profile = getSelectedProfile();
    $('#summary-line').textContent = profile
      ? `${profile.name || profile.mode} — fit and start`
      : DESTINATIONS.console.summary;
  }
}

// The Needs setup metric filters the Profiles table down to the items that
// need attention. It is a control, so it answers to the keyboard as well as
// the pointer (role/tabindex live on the element in index.html).
function showProfilesNeedingSetup() {
  state.profileFilter = 'setup';
  // Also unhide unavailable so the user actually sees the problems.
  state.hideUnavailableProfiles = false;
  const toggle = $('#hide-unavailable-profiles');
  if (toggle) toggle.checked = false;
  renderProfiles();
  showPanel('profiles');
}

const setupWrapper = $('#metric-setup-wrapper');
if (setupWrapper) {
  setupWrapper.addEventListener('click', showProfilesNeedingSetup);
  setupWrapper.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    showProfilesNeedingSetup();
  });
}

function primaryGpu() {
  return state.hardware?.primary_gpu || state.hardware?.gpus?.[0] || null;
}

function detectedThreadDefault() {
  const cpu = state.hardware?.cpu || {};
  return cpu.physical_cores || cpu.logical_cores || PARAM_DEFAULTS.threads;
}

function detectedHeadroomDefault() {
  return state.hardware?.recommended_fit_target_mib || PARAM_DEFAULTS.fit_target_mib;
}

function systemName() {
  return state.hardware?.platform?.system || '';
}

function accelerationOptions() {
  const options = ['auto', ...(primaryGpu()?.acceleration_options || []), 'cpu'];
  if (systemName() === 'Darwin') options.push('metal');
  return Array.from(new Set(options.filter(Boolean).map((value) => String(value).toLowerCase())));
}

function accelerationLabel(value) {
  return {
    auto: 'Auto',
    cuda: 'CUDA',
    vulkan: 'Vulkan',
    hip: 'HIP/ROCm',
    rocm: 'ROCm',
    sycl: 'SYCL',
    metal: 'Metal',
    cpu: 'CPU',
  }[value] || value;
}

function paramDefaults() {
  const threads = detectedThreadDefault();
  return {
    ...PARAM_DEFAULTS,
    threads,
    threads_batch: threads,
    fit_target_mib: detectedHeadroomDefault(),
  };
}

function getSelectedProfile() {
  return state.profiles.find((profile) => profile.mode === state.selectedProfileMode) || state.profiles[0] || null;
}

// Human-readable name for a mode slug, for confirms and toasts. Falls back to
// the slug when the profile is gone (deleted, or not loaded yet).
function profileLabel(mode) {
  const profile = (state.profiles || []).find((item) => item.mode === mode);
  return profile?.name || mode || '';
}

// The single write path for the selected profile. Chat transcripts are stored
// per mode, so every selection change has to repaint #chat-log — otherwise the
// visible transcript belongs to one profile while Send posts to another.
// Returns true when the selection actually moved.
function consoleSummaryLine() {
  const profile = getSelectedProfile();
  if (!profile) return DESTINATIONS.console.summary;
  const endpoint = serverEndpoint(serverRunningForMode(profile.mode));
  return endpoint
    ? `${profile.name || profile.mode} — listening on ${endpoint}`
    : `${profile.name || profile.mode} — fit and start`;
}

function setSelectedProfileMode(mode) {
  const next = mode || null;
  if (state.selectedProfileMode === next) return false;
  state.selectedProfileMode = next;
  renderChatLog(next);
  if ($('.main')?.dataset.destination === 'console') {
    const summary = $('#summary-line');
    if (summary) summary.textContent = consoleSummaryLine();
  }
  return true;
}

function getProfileParams(profile) {
  if (!profile) return {};
  return { ...paramDefaults(), ...(profile.params || {}), ...(state.paramOverrides[profile.mode] || {}) };
}

// Parameter overrides are unsaved work: they used to live only in memory and
// vanish on reload. They now round-trip through localStorage (one entry, keyed
// by profile mode inside it) and are cleared when the profile is saved or reset.
const PARAM_OVERRIDES_KEY = 'lcc-param-overrides';

function persistParamOverrides() {
  try {
    localStorage.setItem(PARAM_OVERRIDES_KEY, JSON.stringify(state.paramOverrides));
  } catch { /* private mode or quota: overrides simply stay in memory */ }
}

function restoreParamOverrides() {
  try {
    const raw = JSON.parse(localStorage.getItem(PARAM_OVERRIDES_KEY));
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) state.paramOverrides = raw;
  } catch { /* malformed entry: start clean */ }
}

const CHAT_HISTORY_KEY = 'lcc-chat-history';
const CHAT_HISTORY_LIMIT = 50;

function persistChatHistory() {
  try {
    const slim = {};
    Object.entries(state.chatHistory || {}).forEach(([mode, entries]) => {
      if (!Array.isArray(entries) || !entries.length) return;
      slim[mode] = entries.slice(-CHAT_HISTORY_LIMIT).map((entry) => ({
        role: entry.role === 'assistant' ? 'assistant' : 'user',
        content: String(entry.content || ''),
      }));
    });
    localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(slim));
  } catch { /* private mode or quota */ }
}

function restoreChatHistory() {
  try {
    const raw = JSON.parse(localStorage.getItem(CHAT_HISTORY_KEY));
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) state.chatHistory = raw;
  } catch { /* malformed entry: start clean */ }
}

function setParamOverrides(mode, overrides) {
  if (!mode) return overrides;
  state.paramOverrides[mode] = overrides;
  persistParamOverrides();
  renderDirtyChip();
  return overrides;
}

function clearParamOverrides(mode) {
  if (!mode) return;
  delete state.paramOverrides[mode];
  persistParamOverrides();
  renderDirtyChip();
}

// Drop drafts for profiles that no longer exist, so a deleted profile cannot
// leave its overrides behind forever.
function pruneParamOverrides() {
  if (!state.profiles.length) return;
  const known = new Set(state.profiles.map((profile) => profile.mode));
  const stale = Object.keys(state.paramOverrides).filter((mode) => !known.has(mode));
  if (!stale.length) return;
  stale.forEach((mode) => delete state.paramOverrides[mode]);
  persistParamOverrides();
}

// Form values arrive as numbers or strings depending on the input type, while
// saved params come back from JSON — compare them as text so 4096 and "4096"
// are not reported as an edit.
function sameParamValue(a, b) {
  if (a === b) return true;
  if (typeof a === 'boolean' || typeof b === 'boolean') return Boolean(a) === Boolean(b);
  return String(a ?? '') === String(b ?? '');
}

function paramOverridesDirty(profile) {
  const overrides = profile && state.paramOverrides[profile.mode];
  if (!overrides) return false;
  const saved = { ...paramDefaults(), ...(profile.params || {}) };
  return Object.keys(overrides).some((key) => !sameParamValue(saved[key], overrides[key]));
}

function renderDirtyChip() {
  const chip = $('#param-dirty-chip');
  if (!chip) return;
  chip.hidden = !paramOverridesDirty(getSelectedProfile());
}

function setFieldValue(id, value) {
  const el = $(id);
  if (!el) return;
  if (el.type === 'checkbox') {
    el.checked = Boolean(value);
  } else {
    el.value = value ?? '';
  }
}

function renderParamProfileOptions() {
  const select = $('#param-profile');
  select.innerHTML = state.profiles.map((profile) => (
    `<option value="${escapeHtml(profile.mode)}">${escapeHtml(profile.name || profile.mode)}</option>`
  )).join('');
  const selected = getSelectedProfile();
  if (selected) select.value = selected.mode;
}

function renderRuntimeOptions(selectedValue) {
  const select = $('#param-runtime');
  if (!select) return;
  const launchableRuntimes = new Set(['llama.cpp', 'vllm-wsl']);
  const envs = state.inventory?.environments || [];
  const options = envs.length
    ? envs.map((env) => ({ value: env.id, label: env.name || env.id, available: env.available }))
    : [{ value: 'llama.cpp', label: 'llama.cpp', available: true }];
  const selected = String(selectedValue || 'llama.cpp');
  if (!options.some((opt) => opt.value === selected)) {
    options.push({ value: selected, label: selected, available: false });
  }
  select.innerHTML = options.map((opt) => {
    const suffix = launchableRuntimes.has(opt.value)
      ? (opt.available ? '' : ' (not detected)')
      : (opt.available ? ' (not launchable yet)' : ' (not detected)');
    return `<option value="${escapeHtml(opt.value)}">${escapeHtml(opt.label)}${suffix}</option>`;
  }).join('');
  select.value = selected;
}

function renderAccelerationOptions(selectedValue) {
  const select = $('#param-acceleration');
  const selected = String(selectedValue || 'auto').toLowerCase();
  const options = accelerationOptions();
  if (!options.includes(selected)) options.push(selected);
  select.innerHTML = options.map((value) => (
    `<option value="${escapeHtml(value)}">${escapeHtml(accelerationLabel(value))}</option>`
  )).join('');
}

function renderParameters() {
  renderParamProfileOptions();
  const profile = getSelectedProfile();
  if (!profile) return;
  const params = getProfileParams(profile);
  renderRuntimeOptions(params.runtime);
  renderAccelerationOptions(params.acceleration_backend);
  setFieldValue('#param-runtime', params.runtime || 'llama.cpp');
  setFieldValue('#param-host', params.host);
  setFieldValue('#param-port', params.port);
  setFieldValue('#param-acceleration', params.acceleration_backend || 'auto');
  setFieldValue('#param-device', params.device || 'auto');
  // Probe the resolved port for the live status dot.
  schedulePortCheck();
  setFieldValue('#param-ctx', params.ctx_size);
  setFieldValue('#param-threads', params.threads);
  setFieldValue('#param-threads-batch', params.threads_batch ?? params.threads);
  setFieldValue('#param-batch', params.batch_size);
  setFieldValue('#param-ubatch', params.ubatch_size);
  setFieldValue('#param-gpu-layers', params.gpu_layers);
  setFieldValue('#param-fit-target', params.fit_target_mib);
  setFieldValue('#param-fit-headroom', params.fit_headroom_mib);
  setFieldValue('#param-cache-k', params.cache_type_k);
  setFieldValue('#param-cache-v', params.cache_type_v);
  setFieldValue('#param-temperature', params.temperature);
  setFieldValue('#param-predict', params.n_predict);
  setFieldValue('#param-top-k', params.top_k);
  setFieldValue('#param-top-p', params.top_p);
  setFieldValue('#param-min-p', params.min_p);
  setFieldValue('#param-repeat-last-n', params.repeat_last_n);
  setFieldValue('#param-repeat-penalty', params.repeat_penalty);
  setFieldValue('#param-presence-penalty', params.presence_penalty);
  setFieldValue('#param-frequency-penalty', params.frequency_penalty);
  setFieldValue('#param-seed', params.seed);
  setFieldValue('#param-draft-model', params.draft_model);
  setFieldValue('#param-flash', params.flash_attn);
  setFieldValue('#param-reasoning', params.reasoning);
  setFieldValue('#param-kv-offload', params.kv_offload);
  setFieldValue('#param-op-offload', params.op_offload);
  setFieldValue('#param-jinja', params.jinja);
  const jinjaHint = $('#param-jinja-hint');
  if (jinjaHint) jinjaHint.hidden = !(state.jinjaRecommended && !$('#param-jinja')?.checked);
  setFieldValue('#param-mmap', params.mmap);
  state.paramPreviewHost = $('#param-host')?.value.trim() || '127.0.0.1';
  state.paramPreviewPort = $('#param-port') ? (Number($('#param-port').value) || 8080) : 8080;
  renderDirtyChip();
  renderLaunchLock();
  scheduleTpsEstimate(80);
}

function numericValue(id) {
  const raw = $(id).value;
  if (raw === '') return undefined;
  return Number(raw);
}

function collectOverrides() {
  return {
    runtime: $('#param-runtime')?.value || 'llama.cpp',
    host: $('#param-host').value.trim() || '127.0.0.1',
    port: numericValue('#param-port'),
    acceleration_backend: $('#param-acceleration').value || 'auto',
    device: $('#param-device').value.trim() || 'auto',
    ctx_size: numericValue('#param-ctx'),
    threads: numericValue('#param-threads'),
    threads_batch: numericValue('#param-threads-batch'),
    batch_size: numericValue('#param-batch'),
    ubatch_size: numericValue('#param-ubatch'),
    gpu_layers: numericValue('#param-gpu-layers'),
    fit_target_mib: numericValue('#param-fit-target'),
    fit_headroom_mib: numericValue('#param-fit-headroom'),
    cache_type_k: $('#param-cache-k').value,
    cache_type_v: $('#param-cache-v').value,
    temperature: numericValue('#param-temperature'),
    n_predict: numericValue('#param-predict'),
    top_k: numericValue('#param-top-k'),
    top_p: numericValue('#param-top-p'),
    min_p: numericValue('#param-min-p'),
    repeat_last_n: numericValue('#param-repeat-last-n'),
    repeat_penalty: numericValue('#param-repeat-penalty'),
    presence_penalty: numericValue('#param-presence-penalty'),
    frequency_penalty: numericValue('#param-frequency-penalty'),
    seed: numericValue('#param-seed'),
    draft_model: $('#param-draft-model').value.trim(),
    flash_attn: $('#param-flash').checked,
    reasoning: $('#param-reasoning').checked,
    kv_offload: $('#param-kv-offload').checked,
    op_offload: $('#param-op-offload').checked,
    jinja: $('#param-jinja').checked,
    mmap: $('#param-mmap').checked,
  };
}

function selectedMode() {
  return $('#param-profile').value || state.selectedProfileMode || state.profiles[0]?.mode;
}

function saveCurrentOverrides() {
  const mode = selectedMode();
  if (!mode) return {};
  return setParamOverrides(mode, collectOverrides());
}

function launchControlState(profile, server, waiting) {
  const live = server && server.running ? server : null;
  const endpoint = serverEndpoint(live);
  return {
    startDisabled: !profile || !profile.launchable || !!live || !!waiting,
    stopDisabled: !live,
    startTitle: live
      ? `Already listening on ${endpoint}`
      : (!profile
        ? 'Select a profile first'
        : (!profile.launchable ? 'This profile is not launchable' : 'Start server')),
    stopTitle: live ? `Stop ${endpoint}` : 'No running server for this profile',
  };
}

function setLaunchWaiting(waiting) {
  const button = $('#start-selected-button');
  const label = $('#start-selected-label');
  if (label) label.textContent = waiting ? 'Waiting to listen' : 'Start server';
  if (button) {
    if (waiting) button.setAttribute('aria-label', 'Waiting for the server to listen');
    else button.removeAttribute('aria-label');
  }
  renderLaunchControls(waiting);
}

function renderLaunchControls(waiting) {
  const profile = getSelectedProfile();
  const live = profile ? serverRunningForMode(profile.mode) : null;
  const start = $('#start-selected-button');
  const isWaiting = waiting ?? !!(start && start.classList.contains('busy'));
  const next = launchControlState(profile, live, isWaiting);
  if (start) {
    start.disabled = next.startDisabled;
    start.title = next.startTitle;
  }
  const stop = $('#stop-selected-button');
  if (stop) {
    stop.disabled = next.stopDisabled;
    stop.title = next.stopTitle;
  }
}

function renderLaunchLock(options = {}) {
  const el = $('#launch-lock');
  if (!el) return;
  const server = serverRunningForMode(selectedMode());
  const copy = launchLockCopy(server);
  const signature = copy ? `${copy.status}|${copy.endpoint}|${copy.detail}` : '';
  const justLocked = !!options.justLocked;
  if (!justLocked && el.dataset.lockSig === signature) {
    renderLaunchControls();
    return;
  }
  if (justLocked && el.dataset.lockSig === signature) {
    el.classList.add('just-locked');
    window.clearTimeout(renderLaunchLock.timer);
    renderLaunchLock.timer = window.setTimeout(() => el.classList.remove('just-locked'), 700);
    return;
  }
  const wasHidden = el.hidden;
  el.dataset.lockSig = signature;
  if (!copy) {
    el.hidden = true;
    el.innerHTML = '';
    el.classList.remove('just-locked');
    el.removeAttribute('aria-label');
  } else {
    el.hidden = false;
    el.classList.toggle('just-locked', justLocked);
    el.setAttribute('aria-label', `Listening on ${copy.endpoint}`);
    el.innerHTML = launchLockHtml(copy);
    if (justLocked) {
      window.clearTimeout(renderLaunchLock.timer);
      renderLaunchLock.timer = window.setTimeout(() => el.classList.remove('just-locked'), 700);
    }
  }
  const mode = selectedMode();
  if (wasHidden !== el.hidden && mode && !(state.chatHistory[mode] || []).length) {
    renderChatLog(mode);
  }
  if ($('.main')?.dataset.destination === 'console') {
    const summary = $('#summary-line');
    if (summary) summary.textContent = consoleSummaryLine();
  }
  renderLaunchControls();
}

function markAppliedFields(params) {
  FIT_APPLIED_FIELDS.forEach(([key, selector]) => {
    const el = $(selector);
    if (!el) return;
    el.classList.toggle('fit-applied', hasOwn(params, key));
  });
  window.clearTimeout(markAppliedFields.timer);
  markAppliedFields.timer = window.setTimeout(() => {
    FIT_APPLIED_FIELDS.forEach(([, selector]) => $(selector)?.classList.remove('fit-applied'));
  }, 4200);
}

function applyFitResultParams(result) {
  const mode = selectedMode();
  if (!mode) return {};
  const applied = { ...collectOverrides(), ...(result.applied_params || {}) };
  const suggestions = result.suggestions || {};
  if (hasOwn(suggestions, 'headroom_mib')) {
    applied.fit_headroom_mib = suggestions.headroom_mib;
  }
  if (hasOwn(suggestions, 'cuda_memory_mib')) {
    applied.fit_cuda_memory_mib = suggestions.cuda_memory_mib;
  }
  setParamOverrides(mode, applied);
  renderParameters();
  markAppliedFields(applied);
  return applied;
}

function runtimeUpdateFor(runtimeId) {
  const updates = state.runtimeUpdates?.updates || [];
  return updates.find((item) => item.runtime_id === runtimeId) || null;
}

function renderRuntimes() {
  const envs = state.inventory?.environments || [];
  const statusEl = $('#runtime-status');
  const updates = state.runtimeUpdates?.updates || [];
  const updateCount = updates.filter((item) => item.update_available).length;
  if (statusEl) {
    const available = envs.filter((env) => env.available).length;
    const suffix = updateCount
      ? ` ${updateCount} update${updateCount === 1 ? '' : 's'} available.`
      : '';
    statusEl.textContent = envs.length
      ? `${available} of ${envs.length} runtime${envs.length === 1 ? '' : 's'} available.${suffix}`
      : 'No runtimes detected.';
  }
  let filteredEnvs = envs;
  if (state.hideNotInstalledRuntimes) {
    filteredEnvs = filteredEnvs.filter((env) => env.available);
  }
  const visibleEnvs = state.showAllRuntimes ? filteredEnvs : filteredEnvs.slice(0, 4);
  const hiddenCount = Math.max(0, filteredEnvs.length - visibleEnvs.length);
  const rows = visibleEnvs.map((env) => {
    const url = runtimeUrl(env);
    const port = runtimePort(env);
    const update = runtimeUpdateFor(env.id || env.kind);
    const isLlamaCpp = env.id === 'llama.cpp' || env.kind === 'local_binary';
    const previewHost = state.paramPreviewHost || '127.0.0.1';
    const previewPort = state.paramPreviewPort || 8080;
    const dynamicUrl = isLlamaCpp ? `http://${previewHost}:${previewPort}` : url;
    const dynamicPort = isLlamaCpp ? String(previewPort) : port;
    const urlDisplay = isLlamaCpp && (url !== `http://${previewHost}:${previewPort}`) ? dynamicUrl : (url || 'Not configured');
    const portDisplay = isLlamaCpp && (port !== String(previewPort)) ? dynamicPort : (port || 'Not configured');
    const urlClass = isLlamaCpp && (url !== `http://${previewHost}:${previewPort}`) ? '' : (url ? '' : 'muted');
    const portClass = isLlamaCpp && (port !== String(previewPort)) ? '' : (port ? '' : 'muted');
    const updateBadge = update?.update_available
      ? `<a class="mini-button icon-button update-badge" href="${escapeHtml(update.release_url || '#')}" target="_blank" rel="noopener noreferrer" title="Update available: ${escapeHtml(update.latest_version || '')} (you have ${escapeHtml(update.current_version || 'unknown')})">v${escapeHtml(update.latest_version || '?')}</a>`
      : '';
    const recheckButton = update
      ? `<button class="mini-button" type="button" data-action="recheck-runtime" data-runtime="${escapeHtml(update.runtime_id)}" title="Recheck this runtime for updates">Recheck</button>`
      : '';
    const actions = `
      <div class="runtime-actions">
        ${updateBadge}${recheckButton}
      </div>
    `;
    const name = isLlamaCpp && env.available ? `${env.name} (CUDA)` : env.name;
    const version = env.version ? `<div class="runtime-version">${escapeHtml(env.version)}</div>` : '';
    return `
      <tr class="runtime-row ${env.available ? 'is-ready' : 'is-missing'}">
        <td>
          <strong>${escapeHtml(name)}</strong>
          ${version}
        </td>
        <td><span class="badge ${env.available ? 'ok' : 'warn'}">${env.available ? 'ready' : 'not found'}</span></td>
        <td>${escapeHtml(env.kind || env.id || 'runtime')}</td>
        <td><code class="${env.binary_path ? '' : 'muted'}" title="${escapeHtml(runtimeLocation(env))}">${escapeHtml(runtimeLocation(env))}</code></td>
        <td><code class="${urlClass}" title="${escapeHtml(urlDisplay)}">${escapeHtml(urlDisplay)}</code></td>
        <td>${escapeHtml(portDisplay)}</td>
        <td>${actions}</td>
      </tr>
    `;
  }).join('');
  const toggle = envs.length > 4
    ? `<div class="runtime-footer"><button class="runtime-more" type="button" data-action="toggle-runtimes">${state.showAllRuntimes ? 'Show fewer runtimes' : `Show ${hiddenCount} more runtimes`} <span aria-hidden="true">${state.showAllRuntimes ? '⌃' : '⌄'}</span></button></div>`
    : '';
  $('#runtime-grid').innerHTML = rows ? `
    <div class="runtime-table-wrap">
      <table class="runtime-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Status</th>
            <th>Type</th>
            <th>Location</th>
            <th>URL</th>
            <th>Port</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    ${toggle}
  ` : emptyStateHtml(runtimesEmptyCopy(envs.length, !!state.hideNotInstalledRuntimes));
}

function serverRunningForMode(mode) {
  const server = state.servers?.find((s) => s.mode === mode && s.running);
  return server || null;
}

function statusBadge(profile) {
  if (profile.launchable) return '<span class="badge ok">Launchable</span>';
  return '<span class="badge warn">Needs setup</span>';
}

function profileIsUnavailable(profile) {
  return !profile.launchable || !profile.model?.path;
}

function filteredProfiles() {
  return state.profiles
    .filter((profile) => {
      if (state.profileFilter === 'launchable') return profile.launchable;
      if (state.profileFilter === 'setup') return !profile.launchable;
      return true;
    })
    .filter((profile) => !state.hideUnavailableProfiles || !profileIsUnavailable(profile))
    .filter((profile) => {
      if (!state.profileModelFilter || state.profileModelFilter === 'all') return true;
      return (profile.model?.name || 'Unresolved model') === state.profileModelFilter;
    })
    .filter(profileMatches);
}

function loadCollapsedGroups() {
  try {
    const stored = localStorage.getItem('lcc-collapsed-groups');
    if (stored) {
      return new Set(JSON.parse(stored));
    }
  } catch { /* ignore */ }
  return new Set();
}

function saveCollapsedGroups(groups) {
  try {
    localStorage.setItem('lcc-collapsed-groups', JSON.stringify([...groups]));
  } catch { /* ignore */ }
}

const collapsedGroups = loadCollapsedGroups();

function groupProfilesByModel(profiles) {
  const groups = {};
  profiles.forEach((profile) => {
    const modelName = profile.model?.name || 'Unresolved model';
    if (!groups[modelName]) {
      groups[modelName] = { model: modelName, profiles: [] };
    }
    groups[modelName].profiles.push(profile);
  });
  return Object.values(groups).sort((a, b) => a.model.localeCompare(b.model));
}

function toggleGroup(modelName) {
  if (collapsedGroups.has(modelName)) {
    collapsedGroups.delete(modelName);
  } else {
    collapsedGroups.add(modelName);
  }
  saveCollapsedGroups(collapsedGroups);
  renderProfiles();
}

function shortModelVariant(profile) {
  const name = profile.model?.name || profile.mode || 'Unresolved model';
  const quant = profile.model?.quant;
  if (quant && !name.toLowerCase().includes(String(quant).toLowerCase())) {
    return `${name.split(/[\\/]/).pop()} ${quant}`;
  }
  return name
    .replace(/-gguf$/i, '')
    .replace(/\.gguf$/i, '')
    .replace(/[-_]+/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

let renderedModelOptions = '';

function updateProfileToolbar(filteredCount) {
  const filterInput = $('#profile-filter-input');
  if (filterInput && filterInput.value !== state.query) filterInput.value = state.query;
  const modelSelect = $('#profile-model-filter');
  if (modelSelect) {
    const models = Array.from(new Set(state.profiles.map((profile) => profile.model?.name || 'Unresolved model'))).sort((a, b) => a.localeCompare(b));
    if (state.profileModelFilter !== 'all' && !models.includes(state.profileModelFilter)) {
      state.profileModelFilter = 'all';
    }
    // Background repaints run through here, so only rebuild the options when
    // the model set really changed — replacing them would close an open
    // dropdown and drop focus mid-selection.
    const optionsHtml = '<option value="all">All models</option>' + models.map((model) => (
      `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`
    )).join('');
    if (renderedModelOptions !== optionsHtml) {
      modelSelect.innerHTML = optionsHtml;
      renderedModelOptions = optionsHtml;
    }
    modelSelect.value = state.profileModelFilter || 'all';
  }
  const availabilityToggle = $('#hide-unavailable-profiles');
  if (availabilityToggle) availabilityToggle.checked = state.hideUnavailableProfiles;
  const filtering = profileFiltersActive();
  const count = $('#profiles-count');
  if (count) {
    count.textContent = filtering
      ? `Showing ${filteredCount} of ${state.profiles.length} profiles`
      : `${state.profiles.length} profile${state.profiles.length === 1 ? '' : 's'}`;
  }
  // "Show all profiles" only means something while something is hidden.
  const viewAll = $('#view-all-profiles');
  if (viewAll) viewAll.hidden = !filtering;
}

function profileFiltersActive() {
  return Boolean(
    state.query.trim()
    || state.hideUnavailableProfiles
    || (state.profileFilter && state.profileFilter !== 'all')
    || (state.profileModelFilter && state.profileModelFilter !== 'all'),
  );
}

// The honest version of the old "View all profiles" no-op anchor: drop every
// filter and search term, which is what actually reveals all of them.
function clearProfileFilters() {
  state.query = '';
  syncSearchInputs('');
  state.profileFilter = 'all';
  state.profileModelFilter = 'all';
  state.hideUnavailableProfiles = false;
  localStorage.setItem('lcc-hide-unavailable-profiles', '0');
  renderProfiles();
  renderModels();
}

function openRenameDialog(mode, currentName) {
  const modal = $('#rename-modal');
  const input = $('#rename-input');
  const okBtn = $('#rename-ok');
  const cancelBtn = $('#rename-cancel');
  input.value = currentName || mode;
  modal.hidden = false;
  document.body.classList.add('modal-open');
  const priorFocus = document.activeElement;
  input.focus();
  input.select();
  return new Promise((resolve) => {
    function cleanup() {
      modal.hidden = true;
      document.body.classList.remove('modal-open');
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
      modal.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      if (priorFocus && typeof priorFocus.focus === 'function') {
        priorFocus.focus();
      }
    }
    function onOk() { cleanup(); resolve(input.value.trim()); }
    function onCancel() { cleanup(); resolve(null); }
    function onBackdrop(event) { if (event.target === modal) onCancel(); }
    function onKey(event) {
      if (event.key === 'Escape') onCancel();
      else if (event.key === 'Enter') { event.preventDefault(); onOk(); }
      else trapTab(event, modal.querySelector('.rename-dialog'));
    }
    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    modal.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);
  });
}

async function saveProfileName(mode, currentName) {
  const newName = await openRenameDialog(mode, currentName);
  if (!newName) return;
  try {
    await api('/api/profiles/name', {
      method: 'POST',
      body: JSON.stringify({ mode, name: newName }),
    });
    toast(`Renamed to "${newName}"`);
    await refresh();
  } catch (error) {
    toast(`Failed to save profile name: ${error.message}`);
  }
}

// Open the row context menu for a profile. Triggered by the row's "..." button
// (data-action="profile-menu"). The menu replaces the previous stub that only
// triggered Rename — Delete is gated by a confirm modal and refuses while a
// tracked server is still running (the backend enforces the same rule).
function openProfileMenu(button, mode) {
  const profile = state.profiles.find((p) => p.mode === mode);
  if (!profile) return;
  const serverRunning = state.servers?.some(
    (server) => server.mode === mode && server.running,
  );
  showPopupMenu(button, [
    {
      label: 'Rename profile…',
      onSelect: () => saveProfileName(mode, profile.name || profile.mode),
    },
    {
      label: 'Save as copy…',
      disabled: !profile.launchable,
      title: profile.launchable
        ? 'Save the current parameters under a new profile name.'
        : 'Profile is not launchable; nothing to copy.',
      onSelect: () => saveProfileAsCopy(profile),
    },
    { separator: true },
    {
      label: 'Delete profile',
      danger: true,
      disabled: serverRunning,
      title: serverRunning
        ? 'A tracked server is still running for this profile. Stop it first.'
        : 'Remove this profile from models.json.',
      onSelect: () => deleteProfileConfirm(mode),
    },
  ]);
}

// Build a manifest ``mode`` from a profile name using the same rule the
// backend applies when it registers a discovered model: every run of
// characters outside [a-zA-Z0-9._-] collapses to a single '-', then trim and
// lowercase. A numeric suffix is appended until the mode is unused.
function uniqueProfileMode(name, fallback = 'profile') {
  let slug = String(name || '')
    .replace(/[^a-zA-Z0-9._-]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase();
  if (!slug) slug = fallback;
  const taken = new Set((state.profiles || []).map((profile) => profile.mode));
  if (!taken.has(slug)) return slug;
  let suffix = 2;
  while (taken.has(`${slug}-${suffix}`)) suffix += 1;
  return `${slug}-${suffix}`;
}

// Create a new models.json entry with its own mode. Never reuses the selected
// profile's mode — that path is Save parameters, and wiring New to it was the
// overwrite foot-gun. Starter params come from defaults, not the open form.
async function createNewProfile(trigger) {
  const selected = state.profiles.find((profile) => profile.mode === state.selectedProfileMode) || null;
  const models = state.inventory?.models || [];
  const unregistered = models.find((model) => !profileForModelPath(state.profiles, model.path));
  const modelPath = selected?.model?.path || unregistered?.path || models[0]?.path || '';
  const modelName = selected?.model?.name || unregistered?.name || models[0]?.name || '';
  if (!modelPath) {
    toast('No model file to attach. Add folders in Settings, then try again.');
    openSettings();
    return;
  }
  const result = await promptProfileDetails({
    title: 'New profile',
    okLabel: 'Create profile',
    name: modelName || 'New profile',
    description: '',
    message: `Creates a new launch config for ${modelName || 'this model'}. Existing profiles stay as they are.`,
  });
  if (!result) return;
  const mode = uniqueProfileMode(result.name);
  const params = paramDefaults();
  await withBusy(trigger, async () => {
    try {
      const saveResult = await api('/api/profiles/save', {
        method: 'POST',
        body: JSON.stringify({
          mode,
          name: result.name,
          description: result.description,
          model_path: modelPath,
          params,
        }),
      });
      if (saveResult.success) {
        toast(saveResult.message || `Created "${result.name}"`);
        await refresh();
        setSelectedProfileMode(mode);
        renderParameters();
        renderProfiles();
      } else {
        toast(saveResult.message || 'Could not create profile');
      }
    } catch (error) {
      toast(`Could not create profile: ${error.message}`);
    }
  });
}

// Save the profile's current parameters under a new name. /api/profiles/save
// matches on ``mode``, so a copy has to carry a fresh mode of its own —
// re-posting the source mode would rename the original instead of duplicating
// it. An unknown mode makes the endpoint append a new manifest entry.
async function saveProfileAsCopy(profile) {
  const result = await promptProfileDetails({
    title: 'Save as copy',
    okLabel: 'Save copy',
    name: `${profile.name || profile.mode} copy`.trim(),
    description: profile.description || '',
    message: `Writes a new profile. "${profile.name || profile.mode}" is left unchanged.`,
  });
  if (!result) return;
  const mode = uniqueProfileMode(result.name, `${profile.mode}-copy`);
  // The parameter form only mirrors the selected profile; for any other row
  // take the params off the profile itself.
  const params = selectedMode() === profile.mode ? collectOverrides() : getProfileParams(profile);
  try {
    const saveResult = await api('/api/profiles/save', {
      method: 'POST',
      body: JSON.stringify({
        mode,
        name: result.name,
        description: result.description,
        model_path: profile.model?.path || '',
        params,
      }),
    });
    if (saveResult.success) {
      toast(saveResult.message || `Saved copy '${result.name}'`);
      await refresh();
    } else {
      toast(saveResult.message || 'Save failed');
    }
  } catch (error) {
    toast(`Save failed: ${error.message}`);
  }
}

async function deleteProfileConfirm(mode) {
  const profile = state.profiles.find((p) => p.mode === mode);
  const displayName = profile?.name || mode;
  const ok = await confirmAction({
    title: 'Delete profile',
    message: `Delete profile "${displayName}" (${mode})? This removes it from models.json. This cannot be undone.`,
    confirmLabel: 'Delete',
    confirmKind: 'danger',
  });
  if (!ok) return;
  try {
    const result = await api('/api/profiles/delete', {
      method: 'POST',
      body: JSON.stringify({ mode }),
    });
    if (result.success) {
      toast(result.message || `Deleted "${displayName}"`);
      if (state.selectedProfileMode === mode) {
        setSelectedProfileMode(null);
      }
      await refresh();
    } else {
      toast(result.message || 'Delete failed');
    }
  } catch (error) {
    toast(`Delete failed: ${error.message}`);
  }
}

function renderProfiles() {
  const profiles = filteredProfiles();
  updateProfileToolbar(profiles.length);
  const groupedProfiles = groupProfilesByModel(profiles);
  let html = '';
  groupedProfiles.forEach((group) => {
    const isCollapsed = collapsedGroups.has(group.model);
    html += `
      <tr class="profile-group-header">
        <td colspan="6">
          <button class="group-toggle" type="button" data-model="${escapeHtml(group.model)}" aria-expanded="${String(!isCollapsed)}" aria-label="${isCollapsed ? 'Expand' : 'Collapse'} ${escapeHtml(group.model)}">
            <span aria-hidden="true">${isCollapsed ? '▸' : '▾'}</span>
            <span>${escapeHtml(group.model)}</span>
            <span class="profile-group-count">${group.profiles.length}</span>
          </button>
        </td>
      </tr>
    `;
    if (!isCollapsed) {
      group.profiles.forEach((profile) => {
        const selected = profile.mode === state.selectedProfileMode;
        html += `
          <tr class="profile-row ${selected ? 'selected' : ''}" data-profile-mode="${escapeHtml(profile.mode)}" tabindex="0" aria-selected="${selected ? 'true' : 'false'}">
            <td data-label="Model">
              <div class="cell-title">${escapeHtml(shortModelVariant(profile))}</div>
            </td>
            <td data-label="Profile">
              <div class="cell-title">${escapeHtml(profile.name || profile.mode)}</div>
              <div class="cell-subtitle">${escapeHtml(profile.mode)}</div>
            </td>
            <td data-label="Fit"><span class="badge ${fitStatusClass(profile.fit_status?.status)}">${escapeHtml(fitStatusLabel(profile.fit_status?.status))}</span></td>
            <td data-label="Port"><code>${escapeHtml(profile.params?.port || '—')}</code></td>
            <td data-label="Status">${statusBadge(profile)}</td>
            <td data-label="Actions">
              <div class="row-actions">
                ${serverRunningForMode(profile.mode)
                  ? `<button class="mini-button danger" type="button" data-action="stop" data-mode="${escapeHtml(profile.mode)}" title="Stop server" aria-label="Stop ${escapeHtml(profile.name || profile.mode)}">Stop</button>`
                  : `<button class="mini-button" type="button" data-action="start" data-mode="${escapeHtml(profile.mode)}" ${profile.launchable ? '' : 'disabled'} title="Start server" aria-label="Start ${escapeHtml(profile.name || profile.mode)}">Start</button>`}
                <button class="mini-button icon-button" type="button" data-action="profile-menu" data-mode="${escapeHtml(profile.mode)}" title="More profile actions" aria-label="More profile actions" aria-haspopup="menu" aria-expanded="false">...</button>
              </div>
            </td>
          </tr>
        `;
      });
    }
  });
  $('#profiles-table').innerHTML = html || emptyStateHtml(
    profilesEmptyCopy(state.profiles.length, profileFiltersActive(), (state.inventory?.models || []).length),
    { tableCell: true },
  );
  renderStageFirstRun();
}

function renderModels() {
  const models = (state.inventory?.models || []).filter(modelMatches);
  $('#model-list').innerHTML = models.map((model) => {
    const profile = profileForModelPath(state.profiles, model.path);
    const actions = profile
      ? `
        <button class="mini-button" type="button" data-model-action="params" data-model-path="${escapeHtml(model.path)}" title="Open this model in the Parameters editor">Parameters</button>
        <button class="mini-button" type="button" data-model-action="fit" data-model-path="${escapeHtml(model.path)}" title="Run a fit test for this model">Fit test</button>
        <button class="mini-button" type="button" data-model-action="tune" data-model-path="${escapeHtml(model.path)}" title="Smart-fit auto-tune this model">Auto-tune</button>
        <button class="mini-button" type="button" data-model-action="hf" data-model-path="${escapeHtml(model.path)}" title="Hugging Face info + update check">HF check</button>`
      : `
        <button class="mini-button primary" type="button" data-model-action="register" data-model-path="${escapeHtml(model.path)}" title="Register this model as a launchable profile">Register</button>`;
    return `
    <article class="model-row">
      <strong>${escapeHtml(model.name)}</strong>
      <div class="model-meta">
        <span class="badge">${escapeHtml(model.quant || 'unknown quant')}</span>
        <span class="badge">${escapeHtml(formatBytes(model.size_bytes))}</span>
        <span class="badge">${escapeHtml(model.source)}</span>
      </div>
      <div class="model-path">${escapeHtml(model.path)}</div>
      <div class="model-actions">${actions}</div>
    </article>`;
  }).join('') || emptyStateHtml(modelsEmptyCopy((state.inventory?.models || []).length, state.query));
  renderStageFirstRun();
}

// Pure matcher: resolve a model file/dir path to its profile. Case- and
// slash-agnostic (Windows paths); prefers launchable exact matches when
// several profiles share one model file (e.g. an MTP variant).
function profileForModelPath(profiles, path) {
  if (!path) return null;
  const norm = (p) => String(p || '').replace(/\//g, '\\').toLowerCase();
  const target = norm(path);
  const matches = (profiles || []).filter((p) => p.model && norm(p.model.path) === target);
  if (!matches.length) return null;
  const ranked = [...matches].sort((a, b) => (
    (b.launchable === true) - (a.launchable === true)
    || (b.confidence === 1.0) - (a.confidence === 1.0)
  ));
  return ranked[0];
}

function formatServerMetricsLine(m) {
  // Pure formatter for AC3: always join non-empty parts with ' · ' (single rule, no ad-hoc concat).
  // Drives the shipped UI display of KV/tps/slots/context/memory.
  if (!m) return '';
  const sum = m.summary || m.metrics || {};
  const proc = m.process || {};
  const parts = [];
  if (sum.kv_cache_usage_ratio != null) parts.push(`${(sum.kv_cache_usage_ratio * 100).toFixed(0)}% KV`);
  if (sum.predicted_tokens_per_second != null) parts.push(`${sum.predicted_tokens_per_second.toFixed(1)} t/s`);
  else if (sum.prompt_tokens_per_second != null) parts.push(`${sum.prompt_tokens_per_second.toFixed(1)} prompt t/s`);
  if (sum.slots_active != null || sum.slots_processing != null) parts.push(`slots ${sum.slots_active || 0}/${sum.slots_processing || 0}`);
  if (m.props && m.props.n_ctx != null) parts.push(`ctx ${m.props.n_ctx}`);
  else if (sum.kv_cache_tokens != null) parts.push(`kv ${sum.kv_cache_tokens}`);
  if (proc.rss_bytes) parts.push(`RSS ${formatBytes(proc.rss_bytes)}`);
  if (proc.gpu_used_bytes) parts.push(`VRAM ${formatBytes(proc.gpu_used_bytes)}`);
  return parts.filter(Boolean).join(' · ');
}

// Pure companion to formatServerMetricsLine: the card gets one dense line, this
// gets the rest of the payload. Returns [{label, value, ratio?}] so the render
// step owns the DOM and this stays testable under node.
//
// A field the payload omits is DROPPED, never rendered. server_metrics returns
// null for llama.cpp-only fields when the server is vLLM, and "NaN%" on screen
// reads as a broken app rather than an absent reading.
function buildServerMetricsRows(m) {
  if (!m) return [];
  const sum = m.summary || {};
  const proc = m.process || {};
  const props = m.props || {};
  const rows = [];
  const push = (label, value, ratio) => {
    if (value === null || value === undefined || value === '') return;
    rows.push(ratio === undefined ? { label, value } : { label, value, ratio });
  };

  if (sum.kv_cache_usage_ratio != null) {
    push('KV cache', `${(sum.kv_cache_usage_ratio * 100).toFixed(0)}%`, sum.kv_cache_usage_ratio);
  }
  if (sum.kv_cache_tokens != null) push('KV tokens', String(sum.kv_cache_tokens));
  if (sum.slots_active != null || sum.slots_processing != null) {
    push('Slots', `${sum.slots_active || 0} active / ${sum.slots_processing || 0} processing`);
  }
  if (sum.predicted_tokens_per_second != null) push('Decode', `${sum.predicted_tokens_per_second.toFixed(1)} t/s`);
  if (sum.prompt_tokens_per_second != null) push('Prompt', `${sum.prompt_tokens_per_second.toFixed(1)} t/s`);
  if (props.n_ctx != null) push('Context', String(props.n_ctx));
  if (proc.rss_bytes) push('Process RSS', formatBytes(proc.rss_bytes));
  if (proc.gpu_used_bytes) push('GPU memory', formatBytes(proc.gpu_used_bytes));
  if (proc.cpu_percent != null) push('CPU', `${Number(proc.cpu_percent).toFixed(0)}%`);
  push('Model', props.model_name);
  push('Build', props.build_info);
  if (m.health && m.health !== 'unknown') push('Health', String(m.health));
  return rows;
}

// Selecting a card here is what the Logs panel reads.
function renderServers() {
  const servers = state.servers || [];
  if (!servers.length) {
    $('#server-box').innerHTML = emptyStateHtml(serversEmptyCopy());
    showLogEmpty();
    return;
  }
  $('#server-box').innerHTML = servers.map((server) => buildServerItemHtml(server)).join('');
  renderServerMetricsPanel();
}

// The Servers poll already carries each server's metrics payload, so the panel
// is a pure re-render off state -- no extra request, no second polling loop.
function renderServerMetricsPanel() {
  const body = $('#server-metrics-body');
  const empty = $('#server-metrics-empty');
  if (!body || !empty) return;
  const servers = state.servers || [];
  const server = servers.find((item) => item.id === state.selectedServerId)
    || servers.find((item) => item.running)
    || servers[0];
  const rows = buildServerMetricsRows(server && server.metrics);
  if (!rows.length) {
    body.hidden = true;
    empty.hidden = false;
    empty.textContent = server
      ? 'No readings yet for this server.'
      : 'No tracked server selected.';
    return;
  }
  empty.hidden = true;
  body.hidden = false;
  body.innerHTML = `
    <div class="metrics-head">${escapeHtml(server.mode || server.id)}</div>
    <dl class="metrics-grid">
      ${rows.map((row) => `
        <div class="metrics-row">
          <dt>${escapeHtml(row.label)}</dt>
          <dd>${escapeHtml(row.value)}${row.ratio === undefined ? '' : `
            <span class="live-bar"><span class="live-bar-fill ${liveBarClass(row.ratio * 100)}" style="width:${Math.min(100, Math.max(0, row.ratio * 100)).toFixed(0)}%"></span></span>`}</dd>
        </div>`).join('')}
    </dl>`;
}

function buildServerItemHtml(server) {
  const isRunning = !!server.running;
  const status = server.status || (isRunning ? 'running' : 'stopped');
  const isCrashed = status === 'crashed' || (!isRunning && server.last_stderr);
  const oom = server.oom_likely ? ' <span class="badge error" title="Likely OOM">OOM</span>' : '';
  const metrics = formatServerMetricsLine(server.metrics);
  const metricsLine = metrics ? `<div class="server-metrics">${escapeHtml(metrics)}</div>` : '';
  const stderrSnippet = (isCrashed && server.last_stderr) ? `<pre class="server-stderr" title="Last stderr (truncated)">${escapeHtml(String(server.last_stderr).slice(0, 300))}</pre>` : '';
  const restartBtn = !isRunning ? `<button class="mini-button" type="button" data-action="restart" data-server-id="${escapeHtml(server.id)}">Restart</button>` : '';
  const stopBtn = `<button class="mini-button" type="button" data-action="stop" data-server-id="${escapeHtml(server.id)}" ${isRunning ? '' : 'disabled'}>Stop</button>`;
  const badgeClass = isCrashed ? 'error' : (isRunning ? 'ok' : 'warn');
  const badgeText = isCrashed ? 'crashed' : (isRunning ? 'running' : status);
  return `
    <article class="server-item${isRunning ? ' running' : ''}${server.id === state.selectedServerId ? ' selected' : ''}" data-server-id="${escapeHtml(server.id)}" tabindex="0" aria-selected="${server.id === state.selectedServerId ? 'true' : 'false'}">
      <span class="badge ${badgeClass}">${escapeHtml(badgeText)}</span>${oom}
      <strong>${escapeHtml(server.mode)}</strong>
      <p>PID ${escapeHtml(server.pid || '-')} on ${escapeHtml(server.host || '127.0.0.1')}:${escapeHtml(server.port || '-')}</p>
      ${metricsLine}
      ${stderrSnippet}
      <div class="row-actions">
        <button class="mini-button" type="button" data-action="logs" data-server-id="${escapeHtml(server.id)}">Open logs</button>
        ${restartBtn}
        ${stopBtn}
      </div>
    </article>`;
}

function renderIssues() {
  // Legacy combined feed for small lists (kept for compatibility).
  const profileIssues = state.profiles
    .filter((profile) => !profile.launchable || profile.warnings?.length)
    .slice(0, 5)
    .map((profile) => ({
      title: profile.mode,
      text: [...(profile.missing || []), ...(profile.warnings || [])].join(' | ') || 'Needs setup',
      kind: profile.launchable ? 'warn' : 'error',
    }));
  const portability = (state.inventory?.portability_issues || []).slice(0, 5).map((issue) => ({
    title: issue.file?.split(/[\\/]/).slice(-1)[0] || 'Portability issue',
    text: `Line ${issue.line}: ${issue.value}`,
    kind: 'warn',
  }));
  const issues = [...profileIssues, ...portability].slice(0, 8);
  $('#issue-list').innerHTML = issues.map((issue) => `
    <article class="issue-item">
      <span class="badge ${issue.kind === 'error' ? 'error' : 'warn'}">${issue.kind === 'error' ? 'Needs setup' : 'Review'}</span>
      <strong>${escapeHtml(issue.title)}</strong>
      <p>${escapeHtml(issue.text)}</p>
    </article>
  `).join('') || '<div class="empty-state">No setup issues detected.</div>';
}

function renderPortability() {
  // Richer view for the reworked Portability & Paths panel.
  const summaryEl = $('#portability-summary');
  if (!summaryEl) return;
  const inv = state.inventory || {};
  const roots = (inv.scan_roots || []).map((r) => escapeHtml(r)).join('<br>') || 'Using defaults';
  const cfg = state.config || {};
  const rtRoots = (cfg.runtime_dirs && cfg.runtime_dirs.length ? cfg.runtime_dirs : (inv.runtime_dirs || [])).map((r) => escapeHtml(r)).join('<br>') || 'Auto (PATH + detected)';
  const issueCount = (inv.portability_issues || []).length + state.profiles.filter((p) => !p.launchable).length;
  summaryEl.innerHTML = `
    <div class="portability-roots">
      <div><strong>Model scan roots</strong><br><span class="mono">${roots}</span></div>
      <div><strong>Runtime search</strong><br><span class="mono">${rtRoots}</span></div>
      <div><strong>Issues surfaced</strong><br><span class="badge ${issueCount ? 'warn' : 'ok'}">${issueCount}</span></div>
    </div>
  `;
  // Also refresh the compact issue list underneath
  renderIssues();
}

// Model Notes keeps HF info, fit-test, and benchmark results in separate slots
// so running a benchmark no longer wipes the fit recommendation (and vice
// versa); each is rendered in its own titled block, clearly separated.
const MODEL_NOTE_TITLES = { hf: 'Hugging Face', tune: 'Smart fit', sampling: 'Sampling preset', fit: 'Fit test', benchmark: 'Benchmark' };

function setModelNote(slot, html) {
  state.modelNotes[slot] = html || '';
  const present = Object.keys(MODEL_NOTE_TITLES).filter((key) => state.modelNotes[key]);
  $('#model-info-box').innerHTML = present.length
    ? present.map((key) => `<div class="note-block"><h3 class="note-block-title">${MODEL_NOTE_TITLES[key]}</h3>${state.modelNotes[key]}</div>`).join('')
    : 'Select a profile, then run HF info or Fit test.';
}

function renderTpsEstimate(estimate) {
  const value = $('#tps-estimate');
  const detail = $('#tps-detail');
  const card = $('#speed-estimate-card');
  if (card) card.classList.add('updating');
  if (!estimate) {
    value.textContent = '-';
    detail.textContent = 'Waiting for model and hardware details.';
    if (card) setTimeout(() => card.classList.remove('updating'), 400);
    return;
  }
  value.textContent = `${estimate.estimate_tps} tok/s`;
  detail.textContent = `${estimate.low_tps}-${estimate.high_tps} tok/s range, ${estimate.confidence} confidence`;
  if (card) setTimeout(() => card.classList.remove('updating'), 400);
}

function renderMeasuredTps(tokensPerSecond, elapsed) {
  const value = $('#tps-estimate');
  const detail = $('#tps-detail');
  if (tokensPerSecond === undefined || tokensPerSecond === null || tokensPerSecond === 0) {
    value.textContent = '-';
    detail.textContent = 'Waiting for model and hardware details.';
    return;
  }
  value.textContent = `${tokensPerSecond} tok/s (measured)`;
  detail.textContent = `Benchmark result: ${elapsed}s elapsed`;
  state.measuredTps = tokensPerSecond;
  state.measuredElapsed = elapsed;
  state.lastBenchmarkKey = estimateKey(selectedMode() || '', collectOverrides());
}

function shouldShowMeasuredTps() {
  if (!state.measuredTps || !state.lastBenchmarkKey) return false;
  const currentKey = estimateKey(selectedMode() || '', collectOverrides());
  return currentKey === state.lastBenchmarkKey;
}

function renderFitEstimate(fit) {
  const value = $('#fit-estimate');
  const detail = $('#fit-detail');
  const card = $('#fit-estimate-card');
  card.classList.remove('status-good', 'status-tight', 'status-near-limit');
  if (card) card.classList.add('updating');
  if (!fit) {
    value.textContent = '-';
    detail.textContent = 'Waiting for model and hardware details.';
    if (card) setTimeout(() => card.classList.remove('updating'), 400);
    return;
  }
  const estimated = fit.estimated || {};
  const status = fit.status || 'unknown';
  value.textContent = fit.label || fitStatusLabel(status);
  if (status === 'good') card.classList.add('status-good');
  if (status === 'tight') card.classList.add('status-tight');
  if (status === 'near_limit') card.classList.add('status-near-limit');
  const details = [
    `VRAM use ${formatMib(estimated.accelerator_used_mib)}`,
    `headroom ${formatMib(estimated.accelerator_headroom_mib)}`,
  ];
  if (fit.uses_ram_offload) {
    details.push(`RAM use ${formatMib(estimated.ram_used_mib)}`);
  }
  detail.textContent = details.join(' · ');
  if (card) setTimeout(() => card.classList.remove('updating'), 400);
}

function clearMeasuredTps() {
  state.measuredTps = null;
  state.measuredElapsed = null;
  state.lastBenchmarkKey = '';
}

function renderEstimatePending(message = 'Estimating launch...') {
  $('#fit-estimate').textContent = '-';
  $('#fit-detail').textContent = message;
  $('#tps-estimate').textContent = '-';
  $('#tps-detail').textContent = message;
  clearMeasuredTps();
}

function estimateKey(mode, overrides) {
  return JSON.stringify({
    mode,
    overrides,
    gpu: primaryGpu()?.name || '',
    vram: primaryGpu()?.vram_total_bytes || 0,
    ram: state.hardware?.memory?.total_bytes || 0,
    cpu: state.hardware?.cpu?.logical_cores || 0,
  });
}

function scheduleTpsEstimate(delay = 350) {
  window.clearTimeout(scheduleTpsEstimate.timer);
  scheduleTpsEstimate.timer = window.setTimeout(updateTpsEstimate, delay);
}

async function updateTpsEstimate() {
  const mode = selectedMode();
  if (!mode) {
    renderTpsEstimate(null);
    renderFitEstimate(null);
    return;
  }
  const overrides = collectOverrides();
  const key = estimateKey(mode, overrides);
  if (state.lastEstimateKey === key) return;
  state.lastEstimateKey = key;
  renderEstimatePending();
  try {
    const result = await api('/api/estimate/launch', {
      method: 'POST',
      body: JSON.stringify({ mode, overrides }),
    });
    renderTpsEstimate(result.speed_estimate);
    renderFitEstimate(result.fit_status);
  } catch (error) {
    $('#fit-estimate').textContent = '-';
    $('#fit-detail').textContent = `Fit unavailable: ${error.message}`;
    $('#tps-estimate').textContent = '-';
    $('#tps-detail').textContent = `Estimate unavailable: ${error.message}`;
  }
}

function formatNumber(value, digits = 2) {
  if (value === undefined || value === null || value === '') return '-';
  if (typeof value === 'boolean') return value ? 'on' : 'off';
  if (typeof value !== 'number') return String(value);
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(digits)));
}

function fitItem(label, value, unit = '') {
  if (value === undefined || value === null || value === '') return '';
  return `<li><span>${escapeHtml(label)}</span><strong>${escapeHtml(formatNumber(value))}${unit}</strong></li>`;
}

function parsedFitAccepted(suggestions) {
  return Object.keys(suggestions || {}).some((key) => key !== 'fitted_args');
}

function fitRecommendation(applied, suggestions) {
  const context = applied.ctx_size ? `${formatNumber(applied.ctx_size)} tokens` : 'the fitted context';
  const layers = hasOwn(applied, 'gpu_layers')
    ? (Number(applied.gpu_layers) >= 999 ? 'all GPU layers' : `${formatNumber(applied.gpu_layers)} GPU layers`)
    : 'the fitted GPU layer count';
  const cache = applied.cache_type_k || applied.cache_type_v
    ? `KV cache ${applied.cache_type_k || '-'} / ${applied.cache_type_v || '-'}`
    : 'the fitted KV cache';
  const headroom = suggestions.headroom_mib || applied.fit_headroom_mib;
  if (headroom) {
    return `Use ${context}, ${layers}, and ${cache}. The fit estimates about ${formatNumber(headroom)} MiB of VRAM headroom after load.`;
  }
  return `Use ${context}, ${layers}, and ${cache}. Re-run with a target headroom if you want a stricter VRAM margin.`;
}

function renderFitSummary(result, applied) {
  const suggestions = result.suggestions || {};
  if (!parsedFitAccepted(suggestions)) {
    const raw = escapeHtml((result.stdout || result.stderr || 'No structured fit suggestion could be parsed.').slice(0, 1800));
    return `<strong>Fit test finished, but no structured recommendation was found.</strong>\n${raw}`;
  }

  const memory = suggestions.cuda_memory_mib || applied.fit_cuda_memory_mib || {};
  const target = applied.fit_target_mib;
  const headroom = suggestions.headroom_mib || applied.fit_headroom_mib;
  const samplingItems = [
    fitItem('Temperature', applied.temperature),
    fitItem('Max tokens', applied.n_predict),
    fitItem('Top K', applied.top_k),
    fitItem('Top P', applied.top_p),
    fitItem('Min P', applied.min_p),
    fitItem('Repeat N', applied.repeat_last_n),
    fitItem('Repeat penalty', applied.repeat_penalty),
    fitItem('Presence penalty', applied.presence_penalty),
    fitItem('Frequency penalty', applied.frequency_penalty),
    fitItem('Seed', applied.seed),
  ].filter(Boolean).join('');
  const memoryItems = [
    fitItem('Context', applied.ctx_size, ' tokens'),
    fitItem('Threads', applied.threads),
    fitItem('Batch threads', applied.threads_batch),
    fitItem('Batch', applied.batch_size),
    fitItem('UBatch', applied.ubatch_size),
    fitItem('GPU layers', Number(applied.gpu_layers) >= 999 ? 'all' : applied.gpu_layers),
    fitItem('Cache K', applied.cache_type_k),
    fitItem('Cache V', applied.cache_type_v),
    fitItem('Target headroom', target, ' MiB'),
    fitItem('Estimated headroom', headroom, ' MiB'),
  ].filter(Boolean).join('');
  const cudaItems = [
    fitItem('Model memory', memory.model, ' MiB'),
    fitItem('Context memory', memory.context, ' MiB'),
    fitItem('Compute memory', memory.compute, ' MiB'),
    fitItem('Projected total', memory.projected, ' MiB'),
  ].filter(Boolean).join('');
  const offloadItems = [
    fitItem('KV cache offload', applied.kv_offload),
    fitItem('CPU helper offload', applied.op_offload),
    fitItem('Flash attention', applied.flash_attn),
    fitItem('Jinja template', applied.jinja),
  ].filter(Boolean).join('');
  const speed = result.speed_estimate;
  const speedItems = speed ? [
    fitItem('Estimated speed', speed.estimate_tps, ' tok/s'),
    fitItem('Likely range', `${speed.low_tps}-${speed.high_tps}`, ' tok/s'),
    fitItem('Confidence', speed.confidence),
  ].filter(Boolean).join('') : '';

  return `
    <div class="fit-summary">
      <div class="fit-status">
        <span class="badge ok">Applied</span>
        <strong>Fit recommendation accepted</strong>
      </div>
      <p>${escapeHtml(fitRecommendation(applied, suggestions))}</p>
      <div class="fit-groups">
        <section>
          <h4>Launch settings</h4>
          <ul>${memoryItems}</ul>
        </section>
        <section>
          <h4>Sampling defaults</h4>
          <ul>${samplingItems}</ul>
        </section>
        ${offloadItems ? `<section><h4>Offload toggles</h4><ul>${offloadItems}</ul></section>` : ''}
        ${cudaItems ? `<section><h4>CUDA estimate</h4><ul>${cudaItems}</ul></section>` : ''}
        ${speedItems ? `<section><h4>Speed estimate</h4><ul>${speedItems}</ul></section>` : ''}
      </div>
      ${suggestions.fitted_args ? `<details class="fit-details"><summary>Fitted CLI args</summary><code>${escapeHtml(suggestions.fitted_args)}</code></details>` : ''}
    </div>
  `;
}

function fitSummaryText(applied, suggestions, speedEstimate) {
  const parts = [
    'Fit recommendation accepted.',
    `Context: ${applied.ctx_size || '-'}`,
    `Threads: ${applied.threads || '-'} / batch ${applied.threads_batch || applied.threads || '-'}`,
    `Batch: ${applied.batch_size || '-'} / ubatch ${applied.ubatch_size || '-'}`,
    `GPU layers: ${Number(applied.gpu_layers) >= 999 ? 'all' : applied.gpu_layers}`,
    `KV cache: K ${applied.cache_type_k || '-'} / V ${applied.cache_type_v || '-'}`,
    `Temperature: ${applied.temperature ?? '-'}`,
  ];
  const headroom = suggestions.headroom_mib || applied.fit_headroom_mib;
  if (headroom) parts.push(`Estimated headroom: ${headroom} MiB`);
  if (speedEstimate?.estimate_tps) parts.push(`Estimated speed: ${speedEstimate.estimate_tps} tok/s`);
  return parts.join('\n');
}

function renderSettings() {
  const config = state.config || {};
  $('#settings-model-dirs').value = listToLines(config.model_dirs);
  $('#settings-runtime-dirs').value = listToLines(config.runtime_dirs);
  $('#settings-llama-server').value = config.llama_server_path || '';
  $('#settings-llama-fit').value = config.llama_fit_params_path || '';
  $('#settings-default-host').value = config.default_host || '127.0.0.1';
  $('#settings-default-port').value = config.default_port || 8080;
  $('#settings-default-backend').value = config.default_backend || 'llama.cpp';
  $('#settings-update-channel').value = config.update_channel || 'stable';
  $('#settings-server-history-limit').value = config.server_history_limit || 5;
  $('#settings-extra-args').value = listToLines(config.extra_llama_args);
  // New/expanded toggles
  const autoScan = $('#settings-auto-scan');
  if (autoScan) autoScan.checked = config.auto_scan_on_startup !== false;
}

function openSettings({ focus = 'model-dirs' } = {}) {
  renderSettings();
  const modal = $('#settings-modal');
  modal.classList.remove('closing');
  modal.hidden = false;
  modal.dataset.openedBy = document.activeElement?.id || '';
  document.body.classList.add('modal-open');
  enhanceTooltips();
  const target = focus === 'runtime-dirs' ? $('#settings-runtime-dirs') : $('#settings-model-dirs');
  target?.focus();
}

function closeSettings() {
  const modal = $('#settings-modal');
  modal.classList.add('closing');
  setTimeout(() => {
    modal.hidden = true;
    modal.classList.remove('closing');
    document.body.classList.remove('modal-open');
    const openerId = modal.dataset.openedBy;
    if (openerId) {
      const opener = document.getElementById(openerId);
      if (opener && typeof opener.focus === 'function') opener.focus();
    } else {
      const button = $('#settings-button');
      if (button) button.focus();
    }
  }, 200);
}

function focusableInside(container) {
  if (!container) return [];
  const selector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  return Array.from(container.querySelectorAll(selector))
    .filter((el) => el.offsetParent !== null || el === document.activeElement);
}

// Shared Tab trap for every modal dialog in the app: while the backdrop is up,
// Tab and Shift+Tab cycle inside ``dialog`` instead of walking into the page
// behind it. Call from a dialog's own keydown handler; non-Tab keys pass through.
function trapTab(event, dialog) {
  if (event.key !== 'Tab' || !dialog) return;
  const items = focusableInside(dialog);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  if (event.shiftKey) {
    if (active === first || !dialog.contains(active)) {
      event.preventDefault();
      last.focus();
    }
  } else if (active === last || !dialog.contains(active)) {
    event.preventDefault();
    first.focus();
  }
}

function detectedRuntimeRoots() {
  const roots = [];
  (state.inventory?.environments || []).forEach((env) => {
    (env.details?.candidate_roots || []).forEach((root) => roots.push(root));
    if (env.binary_path) {
      const normalized = String(env.binary_path).replace(/[\\/][^\\/]+$/, '');
      if (normalized) roots.push(normalized);
    }
  });
  return Array.from(new Set(roots.filter(Boolean)));
}

function collectSettings() {
  return {
    model_dirs: linesToList($('#settings-model-dirs').value),
    runtime_dirs: linesToList($('#settings-runtime-dirs').value),
    llama_server_path: $('#settings-llama-server').value.trim(),
    llama_fit_params_path: $('#settings-llama-fit').value.trim(),
    default_host: $('#settings-default-host').value.trim() || '127.0.0.1',
    default_port: Number($('#settings-default-port').value || 8080),
    default_backend: $('#settings-default-backend').value || 'llama.cpp',
    update_channel: $('#settings-update-channel').value || 'stable',
    server_history_limit: Number($('#settings-server-history-limit').value) || 5,
    extra_llama_args: linesToList($('#settings-extra-args').value),
    auto_scan_on_startup: $('#settings-auto-scan') ? $('#settings-auto-scan').checked : true,
  };
}

async function saveSettings(event) {
  event.preventDefault();
  try {
    const result = await api('/api/config', {
      method: 'POST',
      body: JSON.stringify(collectSettings()),
    });
    state.config = result.config;
    closeSettings();
    toast('Settings saved');
    await refresh();
  } catch (error) {
    toast(`Settings failed: ${error.message}`);
  }
}

// Pure, side-effect free export snapshot builder (for AC2 + testability).
// Takes plain config + optional inventory; returns pretty JSON string.
// No DOM, no state mutation, no network. Directly callable from tests (via vm) and handlers.
function buildPortableExportSnapshot(config, inventory) {
  const c = config || {};
  const inv = inventory || {};
  const snap = {
    schema_version: "lcc-portable-export-v1",
    exported_at: new Date().toISOString(),
    // Core portable roots (the main thing for reproducibility)
    model_dirs: Array.isArray(c.model_dirs) ? [...c.model_dirs] : [],
    runtime_dirs: Array.isArray(c.runtime_dirs) ? [...c.runtime_dirs] : [],
    // Selected direct overrides and defaults (no secrets, no per-profile state)
    llama_server_path: c.llama_server_path || "",
    llama_fit_params_path: c.llama_fit_params_path || "",
    default_host: c.default_host || "127.0.0.1",
    default_port: Number(c.default_port) || 8080,
    default_backend: c.default_backend || "llama.cpp",
    update_channel: c.update_channel || "stable",
    server_history_limit: Number(c.server_history_limit) || 5,
    auto_scan_on_startup: c.auto_scan_on_startup !== false,
    // Discovered scan roots for context (read-only snapshot)
    scan_roots: Array.isArray(inv.scan_roots) ? [...inv.scan_roots] : [],
    // Note: extra_llama_args omitted from minimal portable to keep clean; add if needed
  };
  return JSON.stringify(snap, null, 2);
}

// Plain command registry (pure mapping of id -> real shipped handler fn).
// Directly testable; no DOM creation here. Used by palette and shortcuts (AC3).
// Commands that operate on "the selected profile" need one to exist. Returning
// null after a toast keeps every such command a no-op rather than a silent one.
function requireSelectedProfile() {
  const mode = selectedMode();
  const profile = mode ? state.profiles.find((p) => p.mode === mode) : null;
  if (!profile) {
    toast('Select a profile first');
    return null;
  }
  return profile;
}

// Every entry reuses the same code path as the button that already does the
// job, confirm modals included — the palette is a second door, not a bypass.
const COMMAND_REGISTRY = {
  'focus-search': () => {
    const s = $('#search-input');
    if (s) { s.focus(); s.select(); }
  },
  'open-settings': () => openSettings(),
  'refresh': () => { refresh(); },
  'start-profile': () => {
    const profile = requireSelectedProfile();
    if (profile) startProfile(profile.mode, $('#start-selected-button'));
  },
  'stop-profile': () => {
    const profile = requireSelectedProfile();
    if (profile) stopProfileByMode(profile.mode, $('#stop-selected-button'));
  },
  'restart-profile': () => {
    const profile = requireSelectedProfile();
    if (!profile) return;
    const tracked = (state.servers || []).find((server) => server.mode === profile.mode);
    if (!tracked) {
      toast(`No tracked server for "${profileLabel(profile.mode)}" to restart`);
      return;
    }
    restartTracked(tracked.id, null);
  },
  'smart-fit': () => {
    if (requireSelectedProfile()) runAutoTune();
  },
  'fit-test': () => {
    if (requireSelectedProfile()) runFitTest();
  },
  'benchmark': () => {
    if (requireSelectedProfile()) runBenchmark();
  },
  'open-logs': () => {
    const serverId = state.selectedServerId || state.servers[0]?.id;
    if (!serverId) {
      toast('No tracked server to open logs for');
      return;
    }
    loadLogs(serverId);
    showPanel('logs');
  },
  'purge-stopped': () => { purgeServers(true, $('#servers-purge-stopped')); },
  'toggle-theme': () => cycleTheme(),
  'new-profile': () => createNewProfile($('#new-profile-button')),
  'save-profile-copy': () => {
    const profile = requireSelectedProfile();
    if (!profile) return;
    if (!profile.launchable) {
      toast('Selected profile is not launchable; nothing to copy');
      return;
    }
    saveProfileAsCopy(profile);
  },
};

// Static by design: the palette list is a pure value, so it stays testable
// outside the DOM. Availability is decided when a command runs, not here.
function getCommands() {
  return [
    { id: 'focus-search', label: 'Focus search', shortcut: 'Ctrl+K' },
    { id: 'start-profile', label: 'Start selected profile' },
    { id: 'stop-profile', label: 'Stop selected profile' },
    { id: 'restart-profile', label: 'Restart selected profile' },
    { id: 'smart-fit', label: 'Smart fit selected profile' },
    { id: 'fit-test', label: 'Run fit test' },
    { id: 'benchmark', label: 'Run benchmark' },
    { id: 'open-logs', label: 'Open logs' },
    { id: 'purge-stopped', label: 'Purge stopped servers' },
    { id: 'new-profile', label: 'New profile…' },
    { id: 'save-profile-copy', label: 'Save profile as copy…' },
    { id: 'toggle-theme', label: 'Cycle theme (light / dark / system)' },
    { id: 'open-settings', label: 'Open Settings' },
    { id: 'refresh', label: 'Refresh inventory' },
  ];
}

function executeCommand(id) {
  const fn = COMMAND_REGISTRY[id];
  if (typeof fn === 'function') {
    fn();
    return true;
  }
  return false;
}

async function exportPortableConfig(trigger) {
  try {
    const json = buildPortableExportSnapshot(state.config, state.inventory);
    // Use clipboard API (modern browsers); fallback to toast with text if blocked
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(json);
      toast('Portable config copied to clipboard');
    } else {
      // Rare fallback: show in toast + console for manual copy
      toast('Export ready (clipboard unavailable) — see console');
      console.log('LCC portable export:\n' + json);
    }
    // Also briefly show a hint in model notes or just rely on toast
  } catch (err) {
    toast('Export failed: ' + (err && err.message ? err.message : err));
  }
}

let paletteVisible = false;
let paletteReturnFocus = null;
function showCommandPalette() {
  const back = $('#command-palette');
  if (!back) return;
  paletteReturnFocus = document.activeElement;
  back.hidden = false;
  document.body.classList.add('modal-open');
  paletteVisible = true;
  renderPaletteList('');
  const filter = $('#palette-filter');
  if (filter) {
    filter.value = '';
    filter.focus();
    filter.oninput = () => renderPaletteList(filter.value);
    // Basic keyboard nav for palette list (up/down/enter)
    filter.onkeydown = (ev) => {
      const items = Array.from($('#palette-list').querySelectorAll('li[data-cmd]'));
      if (!items.length) return;
      let sel = items.findIndex(i => i.classList.contains('selected'));
      if (sel < 0) sel = 0;
      if (ev.key === 'ArrowDown') {
        ev.preventDefault();
        sel = (sel + 1) % items.length;
        setPaletteSelection(items, sel);
      } else if (ev.key === 'ArrowUp') {
        ev.preventDefault();
        sel = (sel - 1 + items.length) % items.length;
        setPaletteSelection(items, sel);
      } else if (ev.key === 'Enter') {
        ev.preventDefault();
        const chosen = items[sel >=0 ? sel : 0];
        if (chosen) {
          const id = chosen.dataset.cmd;
          hideCommandPalette();
          executeCommand(id);
        }
      }
    };
  }
}
function hideCommandPalette() {
  const back = $('#command-palette');
  if (back) back.hidden = true;
  document.body.classList.remove('modal-open');
  paletteVisible = false;
  // Hand the keyboard back to whatever had it before the palette opened.
  // A command that moves focus itself (Focus search) runs after this and wins.
  if (paletteReturnFocus && typeof paletteReturnFocus.focus === 'function') {
    paletteReturnFocus.focus({ preventScroll: true });
  }
  paletteReturnFocus = null;
}
// Focus stays in the filter box, so the highlighted row is announced through
// aria-activedescendant rather than by moving focus into the list.
function setPaletteSelection(items, index) {
  items.forEach((item, idx) => {
    const active = idx === index;
    item.classList.toggle('selected', active);
    item.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  const current = items[index];
  if (!current) return;
  current.scrollIntoView({ block: 'nearest' });
  $('#palette-filter')?.setAttribute('aria-activedescendant', current.id);
}

function renderPaletteList(filterText) {
  const list = $('#palette-list');
  if (!list) return;
  const q = (filterText || '').toLowerCase().trim();
  const cmds = getCommands().filter(c => !q || c.label.toLowerCase().includes(q) || c.id.includes(q));
  list.innerHTML = cmds.map((c) => `
    <li id="palette-option-${escapeHtml(c.id)}" role="option" aria-selected="false" data-cmd="${escapeHtml(c.id)}">
      <span>${escapeHtml(c.label)}</span>
      ${c.shortcut ? `<kbd>${escapeHtml(c.shortcut)}</kbd>` : ''}
    </li>
  `).join('') || '<li class="empty" role="presentation">No matching commands</li>';
  // click to execute
  const items = Array.from(list.querySelectorAll('li[data-cmd]'));
  items.forEach(li => {
    li.addEventListener('click', () => {
      const id = li.dataset.cmd;
      hideCommandPalette();
      executeCommand(id);
    });
  });
  if (items.length) setPaletteSelection(items, 0);
  else $('#palette-filter')?.removeAttribute('aria-activedescendant');
}

function updateHfCliUi(hfData) {
  const statusBadge = $('#hf-cli-status');
  const versionEl = $('#hf-cli-version');
  const pathEl = $('#hf-cli-path');
  if (!hfData) return;
  if (hfData.installed) {
    statusBadge.textContent = 'Installed';
    statusBadge.className = 'badge ok';
  } else {
    statusBadge.textContent = 'Not installed';
    statusBadge.className = 'badge warn';
  }
  versionEl.textContent = hfData.version || '-';
  pathEl.textContent = hfData.binary_path || '-';
}

async function suggestDraftModels() {
  const trigger = $('#suggest-draft-button');
  const container = $('#draft-suggestions');
  const profile = getSelectedProfile();
  if (!profile) return;
  await withBusy(trigger, async () => {
    try {
      // api() is a thin fetch wrapper with no query-string support, so the
      // model name has to be encoded into the path (same as checkPortNow).
      const qs = `model_name=${encodeURIComponent(profile.model?.name || '')}`;
      const result = await api(`/api/draft-models/suggest?${qs}`);
      const suggestions = result.suggestions || [];
      if (suggestions.length === 0) {
        container.innerHTML = '<div class="empty-state">No draft model suggestions available for this model.</div>';
        container.hidden = false;
        return;
      }
      container.innerHTML = suggestions.map((s, idx) => `
        <div class="draft-suggestion-item">
          <div>
            <div class="draft-name">${escapeHtml(s.name)}</div>
            <div class="draft-desc">${escapeHtml(s.description || '')} · ${escapeHtml(s.recommended_quant || 'Q4_K_M')}</div>
          </div>
          <button class="mini-button" type="button" data-draft-idx="${idx}" data-draft-repo="${escapeHtml(s.repo_id || '')}">Pull</button>
        </div>
      `).join('');
      container.hidden = false;
      container.querySelectorAll('[data-draft-idx]').forEach((btn) => {
        btn.addEventListener('click', async (event) => {
          const repoId = event.target.dataset.draftRepo;
          await pullDraftModel(repoId, event.target);
        });
      });
    } catch (error) {
      toast(`Draft suggestions failed: ${error.message}`);
    }
  });
}

async function pullDraftModel(repoId, trigger) {
  const container = $('#draft-suggestions');
  const originalText = trigger.textContent;
  trigger.textContent = 'Pulling...';
  trigger.disabled = true;
  try {
    const result = await api('/api/draft-models/pull', {
      method: 'POST',
      body: JSON.stringify({ repo_id: repoId, quant: 'Q4_K_M' }),
    });
    if (result.success) {
      toast(`Draft model pulled from ${repoId}`);
      container.innerHTML = `<div class="draft-suggestion-item"><div><div class="draft-name">Pulled!</div><div class="draft-desc">${escapeHtml(result.message)}</div></div></div>`;
    } else {
      toast(result.message || 'Pull failed');
    }
  } catch (error) {
    toast(`Pull failed: ${error.message}`);
  } finally {
    trigger.textContent = originalText;
    trigger.disabled = false;
  }
}

// Each resource fetches independently and repaints only its own sections as it
// resolves, so the dashboard paints progressively instead of blocking on the
// slowest endpoint (runtime-updates hits GitHub on a cold cache). Cross-cutting
// renders (e.g. renderSummary needs inventory+profiles) are listed on every
// input they read — idempotent, so running them more than once is harmless.
function reconcileSelectedMode() {
  if (!state.selectedProfileMode && state.profiles.length) {
    setSelectedProfileMode(state.profiles[0].mode);
  } else if (state.selectedProfileMode && !state.profiles.some((profile) => profile.mode === state.selectedProfileMode)) {
    setSelectedProfileMode(state.profiles[0]?.mode || null);
  }
}

const DASHBOARD_RESOURCES = [
  { label: 'profiles', path: '/api/profiles', apply: (d) => { state.profiles = d.profiles || []; }, render: () => { pruneParamOverrides(); reconcileSelectedMode(); renderProfiles(); renderParameters(); renderSummary(); } },
  { label: 'servers', path: '/api/servers', apply: (d) => { state.servers = d.servers || []; }, render: renderServers },
  { label: 'inventory', path: '/api/inventory', apply: (d) => { state.inventory = d; }, render: () => { renderSummary(); renderModels(); renderIssues(); renderRuntimes(); renderRuntimeOptions($('#param-runtime')?.value); renderPortability(); } },
  { label: 'settings', path: '/api/config', apply: (d) => { state.config = d; }, render: () => { renderSettings(); renderParameters(); renderPortability(); } },
  { label: 'hardware', path: '/api/system', apply: (d) => { state.hardware = d; }, render: renderParameters },
  { label: 'meta', path: '/api/meta', apply: (d) => { state.meta = d; }, render: renderVersion },
  { label: 'runtime-updates', path: '/api/runtime-updates', apply: (d) => { state.runtimeUpdates = d; }, render: renderRuntimes },
  { label: 'hf-cli', path: '/api/hf-cli', apply: (d) => { updateHfCliUi(d); }, render: () => {} },
  { label: 'benchmarks', path: '/api/benchmarks', apply: (d) => { state.benchmarks = d.benchmarks || []; }, render: renderBenchmarkHistory },
];

// The background server poll uses these two to tell whether its in-flight
// response is still the freshest view of the world.
let refreshInFlight = false;
let refreshGeneration = 0;

async function refresh() {
  const refreshButton = $('#refresh-button');
  if (refreshButton) {
    refreshButton.disabled = true;
    refreshButton.setAttribute('aria-busy', 'true');
  }
  setApiStatus(false, 'Refreshing');
  state.lastEstimateKey = '';
  refreshInFlight = true;
  try {
    const failures = (await Promise.all(DASHBOARD_RESOURCES.map(async (resource) => {
      const error = await loadDashboardResource(resource.label, resource.path, resource.apply);
      if (!error) resource.render();
      return error;
    }))).filter(Boolean);
    if (failures.length) {
      const summary = failures.slice(0, 2).join('; ');
      const suffix = failures.length > 2 ? ` and ${failures.length - 2} more` : '';
      const detailText = failures.join('\n');
      setApiStatus(false, failures.length >= DASHBOARD_RESOURCES.length ? 'API error' : 'API partial', detailText);
      toast(`Refresh partial: ${summary}${suffix}`);
    } else {
      setApiStatus(true, 'API ready');
    }

    // M2 observability (M1.3/M2.1): extend polling to fetch /metrics for running/crashed
    // servers on refresh. Attach to the server objects in state so renderers can use them.
    // Logs remain on-demand via loadLogs (already wired in UI).
    try {
      const servers = state.servers || [];
      const toPoll = servers.filter((s) => s.running || s.status === 'crashed' || s.status === 'startup_timeout');
      if (toPoll.length > 0) {
        await Promise.all(toPoll.map(async (srv) => {
          try {
            const m = await api(`/api/servers/${encodeURIComponent(srv.id)}/metrics`);
            srv.metrics = m;
          } catch (_) {
            // non-fatal; render will show what it has
          }
        }));
        renderServers();
      }
    } catch (_) {
      // enrichment must never break refresh
    }
  } catch (error) {
    setApiStatus(false, 'API error', `API error: ${error.message}`);
    toast(`Refresh failed: ${error.message}`);
  } finally {
    refreshInFlight = false;
    refreshGeneration += 1;
    if (refreshButton) {
      refreshButton.disabled = false;
      refreshButton.removeAttribute('aria-busy');
    }
    scheduleServerPoll();
  }
}

async function refreshRuntimeUpdates(trigger) {
  await withBusy(trigger, async () => {
    try {
      const data = await api('/api/runtime-updates/refresh', { method: 'POST' });
      state.runtimeUpdates = data;
      renderRuntimes();
      const updates = data.updates || [];
      const available = updates.filter((item) => item.update_available).length;
      const skippedNoVersion = data.skipped_no_version || [];
      const skippedUnsupported = data.skipped_unsupported || [];
      if (data.checked_runtime_count === 0 && data.known_runtime_count === 0) {
        toast('No runtimes detected that support update checks.');
      } else if (data.checked_runtime_count === 0) {
        const reasons = [];
        if (skippedNoVersion.length) reasons.push(`${skippedNoVersion.join(', ')} (no version detected)`);
        if (skippedUnsupported.length) reasons.push(`${skippedUnsupported.join(', ')} (not tracked)`);
        toast(`No update checks ran: ${reasons.join('; ')}`);
      } else if (!available) {
        toast('All runtimes are up to date');
      } else {
        toast(`${available} runtime update${available === 1 ? '' : 's'} available`);
      }
    } catch (error) {
      toast(`Update check failed: ${error.message}`);
    }
  });
}

async function recheckRuntime(runtimeId, trigger) {
  await withBusy(trigger, async () => {
    try {
      const data = await api(`/api/runtime-updates/refresh?runtime=${encodeURIComponent(runtimeId)}`, { method: 'POST' });
      state.runtimeUpdates = data;
      renderRuntimes();
      const update = (data.updates || []).find((item) => item.runtime_id === runtimeId);
      if (update?.update_available) toast(`${runtimeId}: update v${update.latest_version} available`);
      else if (update) toast(`${runtimeId} is up to date`);
      else toast(`${runtimeId}: no update info`);
    } catch (error) {
      toast(`Recheck failed: ${error.message}`);
    }
  });
}

async function prepareProfile(mode, trigger) {
  const targetMode = mode || selectedMode();
  if (!targetMode) {
    toast('No profile selected');
    return;
  }
  setSelectedProfileMode(targetMode);
  const overrides = collectOverrides();
  await withBusy(trigger, async () => {
    try {
      const result = await api('/api/servers/prepare', {
        method: 'POST',
        body: JSON.stringify({ mode: targetMode, overrides }),
      });
      if (!result.success) {
        toast(result.message || 'Could not build the launch command');
        return;
      }
      showLogPreview(result.command?.command_line || 'Launch command unavailable.');
      revealPanel('logs');
      renderProfiles();
      renderParameters();
      toast(`Launch command for "${profileLabel(targetMode)}" is in Logs`);
    } catch (error) {
      toast(`Could not build the launch command: ${error.message}`);
    }
  });
}

async function startProfile(mode, trigger) {
  const targetMode = mode || selectedMode();
  if (!targetMode) {
    toast('No profile selected');
    return;
  }
  setSelectedProfileMode(targetMode);
  const host = $('#param-host')?.value.trim() || '127.0.0.1';
  const port = $('#param-port')?.value || '';
  const where = port ? `${host}:${port}` : host;
  const confirmed = await confirmAction({
    title: 'Start server',
    message: `Start "${profileLabel(targetMode)}" on ${where} with the current parameters?`,
    confirmLabel: 'Start',
    confirmKind: 'primary',
  });
  if (!confirmed) return;
  const overrides = collectOverrides();
  setActionsBusy(targetMode, true);
  setLaunchWaiting(true);
  try {
    const result = await withBusy(trigger, () => api('/api/servers/start', {
      method: 'POST',
      body: JSON.stringify({ mode: targetMode, overrides, wait_ready: true, ready_timeout_seconds: 45 }),
    }));
    toast(listeningToast(result.server, profileLabel(targetMode)), {
      label: 'Open Chat',
      onClick: () => showPanel('chat'),
    });
    await refresh();
    renderProfiles();
    renderLaunchLock({ justLocked: true });
  } catch (error) {
    const detail = error.detail;
    if (detail && detail.port_in_use) {
      const suggested = detail.suggested_port;
      if (detail.port_in_use_reason === 'reserved') {
        // Windows-reserved-range case: no holder to report, but the
        // suggested_port is already chosen above the range end.
        const rng = detail.reserved_range || {};
        toast(
          `Port ${detail.port} is inside the Windows reserved range ${rng.start ?? '?'}-${rng.end ?? '?'}. Pick a port above ${rng.end ?? '?'}.`,
          suggested
            ? {
                label: `Use port ${suggested}`,
                onClick: () => {
                  const portInput = $('#param-port');
                  if (portInput) {
                    portInput.value = String(suggested);
                    portInput.dispatchEvent(new Event('input', { bubbles: true }));
                    portInput.focus();
                  }
                },
              }
            : undefined,
        );
      } else {
        const holder = detail.port_holder || {};
        const who = holder.process_name && holder.pid
          ? `${holder.process_name} (PID ${holder.pid})`
          : holder.process_name || holder.pid || 'another process';
        toast(
          `Port ${detail.port} is already bound by ${who}.`,
          suggested
            ? {
                label: `Use port ${suggested}`,
                onClick: () => {
                  const portInput = $('#param-port');
                  if (portInput) {
                    portInput.value = String(suggested);
                    portInput.dispatchEvent(new Event('input', { bubbles: true }));
                    portInput.focus();
                  }
                },
              }
            : undefined,
        );
      }
    } else {
      toast(`Start failed: ${error.message}`);
    }
  } finally {
    setLaunchWaiting(false);
    setActionsBusy(targetMode, false);
  }
}

function tuneFieldLabel(field) {
  return {
    gpu_layers: 'GPU layers',
    ctx_size: 'Context',
    cache_type_k: 'KV cache K',
    cache_type_v: 'KV cache V',
  }[field] || field;
}

function tuneValueLabel(field, value) {
  if (field === 'gpu_layers') return Number(value) >= 999 || value === 'all' ? 'all' : formatNumber(value);
  return value ?? '-';
}

function shouldAutoApplyTune(result) {
  return !!(result && result.success && !result.cpu_fallback);
}

function renderTuneNotes(notes) {
  if (!Array.isArray(notes) || !notes.length) return '';
  return `<ul class="tune-notes">${notes.map((note) => `<li>${escapeHtml(note)}</li>`).join('')}</ul>`;
}

function renderTuneSummary(result, options = {}) {
  const applied = options.applied === true;
  const before = result.before?.fit_status || {};
  const after = result.after?.fit_status || {};
  const beforeSpeed = result.before?.speed_estimate || {};
  const afterSpeed = result.after?.speed_estimate || {};
  const changeItems = (result.changes || []).map((c) => (
    `<li><span>${escapeHtml(tuneFieldLabel(c.field))}</span><strong>${escapeHtml(String(tuneValueLabel(c.field, c.from)))} → ${escapeHtml(String(tuneValueLabel(c.field, c.to)))}</strong></li>`
  )).join('') || '<li><span>No changes</span><strong>already optimal</strong></li>';
  const reasons = (result.changes || []).map((c) => `<li>${escapeHtml(c.why)}</li>`).join('');
  const title = result.cpu_fallback
    ? 'GPU cannot hold this model'
    : (applied ? 'Auto-tuned for best fit' : 'Smart fit ready');
  const badgeStatus = result.cpu_fallback ? 'tight' : after.status;
  const applyButton = applied
    ? ''
    : '<button class="mini-button" type="button" data-tune-index="0">Apply CPU recommendation</button>';
  return `
    <div class="fit-summary">
      <div class="fit-status">
        <span class="badge ${fitStatusClass(badgeStatus)}">${escapeHtml(result.cpu_fallback ? 'CPU' : fitStatusLabel(after.status))}</span>
        <strong>${escapeHtml(title)}</strong>
        ${applyButton}
      </div>
      ${renderTuneNotes(result.notes)}
      <div class="fit-groups">
        <section>
          <h4>${applied ? 'Changes applied' : 'Proposed changes'}</h4>
          <ul>${changeItems}</ul>
        </section>
        <section>
          <h4>Fit &amp; speed</h4>
          <ul>
            ${fitItem('Fit', `${fitStatusLabel(before.status)} → ${fitStatusLabel(after.status)}`)}
            ${fitItem('Est. speed', `${beforeSpeed.estimate_tps ?? '-'} → ${afterSpeed.estimate_tps ?? '-'}`, ' tok/s')}
          </ul>
        </section>
      </div>
      ${renderTuneSuggestions(result.suggestions)}
      ${reasons ? `<details class="fit-details"><summary>Why these changes</summary><ul>${reasons}</ul></details>` : ''}
    </div>
  `;
}

function renderTuneSuggestions(suggestions) {
  if (!Array.isArray(suggestions) || suggestions.length <= 1) return '';
  const cards = suggestions.map((s, index) => {
    const p = s.params || {};
    const fit = s.fit_status || {};
    const speed = s.speed_estimate || {};
    const cache = p.cache_type_k === p.cache_type_v
      ? (p.cache_type_k ?? '-')
      : `${p.cache_type_k ?? '-'}/${p.cache_type_v ?? '-'}`;
    const specs = [
      `Ctx ${formatNumber(p.ctx_size)}`,
      `KV ${escapeHtml(String(cache))}`,
      `${fitStatusLabel(fit.status)} fit`,
      `~${speed.estimate_tps ?? '-'} tok/s`,
    ].map((t) => `<span>${escapeHtml(t)}</span>`).join('');
    return `
      <div class="tune-suggestion">
        <div class="tune-suggestion-head">
          <strong>${escapeHtml(s.label || s.intent || 'Option')}</strong>
          <button class="mini-button" type="button" data-tune-index="${index}">Apply</button>
        </div>
        <p>${escapeHtml(s.description || '')}</p>
        <div class="tune-suggestion-specs">${specs}</div>
      </div>`;
  }).join('');
  return `<section class="tune-suggestions"><h4>Suggestions for your need</h4>${cards}</section>`;
}

function applyTuneSuggestion(index) {
  const suggestion = (state.tuneSuggestions || [])[index];
  if (!suggestion) return;
  applyTunedParams(suggestion.params);
  renderTpsEstimate(suggestion.speed_estimate);
  scheduleTpsEstimate(80);
  toast(`Applied ${suggestion.label || 'suggestion'}`);
}

function applyTunedParams(tuned) {
  const mode = selectedMode();
  if (!mode) return {};
  const applied = { ...collectOverrides(), ...(tuned || {}) };
  setParamOverrides(mode, applied);
  renderParameters();
  markAppliedFields(tuned || {});
  return applied;
}

async function runAutoTune() {
  const mode = selectedMode();
  if (!mode) return;
  setSelectedProfileMode(mode);
  const overrides = saveCurrentOverrides();
  const trigger = $('#smart-fit-button');
  setModelNote('tune', 'Searching for the best memory fit...');
  await withBusy(trigger, async () => {
    try {
      const result = await api('/api/profiles/auto-tune', {
        method: 'POST',
        body: JSON.stringify({ mode, overrides }),
      });
      if (!result.success) {
        setModelNote('tune', `<strong>Could not auto-tune</strong>\n${escapeHtml(result.reason || 'No fitting configuration found.')}`);
        toast('Smart fit found no safe configuration');
        return;
      }
      state.tuneSuggestions = result.suggestions || [];
      state.jinjaRecommended = !!(result.jinja && result.jinja.recommended);
      const applied = shouldAutoApplyTune(result);
      if (applied) {
        applyTunedParams(result.tuned_params);
        renderTpsEstimate(result.after?.speed_estimate);
        scheduleTpsEstimate(80);
      }
      setModelNote('tune', renderTuneSummary(result, { applied }));
      if (result.cpu_fallback) toast('Smart fit held back a CPU recommendation');
      else toast(applied ? 'Smart fit applied' : 'Smart fit ready');
    } catch (error) {
      setModelNote('tune', `<strong>Smart fit failed</strong>\n${escapeHtml(error.message)}`);
      toast(`Smart fit failed: ${error.message}`);
    }
  });
}

// Select the profile that owns `path` in the Parameters editor (same code
// path as the #param-profile dropdown), returning the profile or null.
function selectProfileForModelPath(path) {
  const profile = profileForModelPath(state.profiles, path);
  if (!profile) {
    toast('No profile for this model yet — click Register first');
    return null;
  }
  setSelectedProfileMode(profile.mode);
  const select = $('#param-profile');
  if (select) select.value = profile.mode;
  renderParameters();
  renderProfiles();
  return profile;
}

async function handleModelAction(action, path, trigger) {
  if (action === 'register') {
    await withBusy(trigger, async () => {
      try {
        const result = await api('/api/profiles/scan', {
          method: 'POST',
          body: JSON.stringify({ model_path: path || '' }),
        });
        toast(result.registered_count
          ? `Registered ${result.registered_count} profile${result.registered_count === 1 ? '' : 's'} for this model`
          : 'No new profile for this model');
        await refresh();
      } catch (error) {
        toast(`Register failed: ${error.message}`);
      }
    });
    return;
  }
  const profile = selectProfileForModelPath(path);
  if (!profile) return;
  if (action === 'params') {
    showPanel('parameters');
  } else if (action === 'fit') {
    await runFitTest();
  } else if (action === 'tune') {
    await runAutoTune();
  } else if (action === 'hf') {
    await fetchHFInfo();
    await checkModelUpdate();
  }
}

async function loadSamplingPresets() {
  const select = $('#sampling-intent');
  if (!select) return;
  try {
    const data = await api('/api/sampling/presets');
    state.samplingPresets = data.presets || {};
    select.innerHTML = (data.intents || []).map((intent) => (
      `<option value="${escapeHtml(intent.key)}" title="${escapeHtml(intent.description)}">${escapeHtml(intent.label)}</option>`
    )).join('');
  } catch (error) {
    select.innerHTML = '<option value="">Presets unavailable</option>';
  }
}

function applySamplingPreset() {
  const mode = selectedMode();
  if (!mode) return;
  const intent = $('#sampling-intent')?.value;
  const preset = state.samplingPresets?.[intent];
  if (!preset?.success) {
    toast('Choose a sampling preset first');
    return;
  }
  setSelectedProfileMode(mode);
  setParamOverrides(mode, { ...saveCurrentOverrides(), ...preset.params });
  renderParameters();
  markAppliedFields(preset.params);
  const rationale = Object.entries(preset.rationale || {})
    .map(([field, why]) => `<li><strong>${escapeHtml(field)}:</strong> ${escapeHtml(why)}</li>`)
    .join('');
  const paramItems = [
    fitItem('Temperature', preset.params.temperature),
    fitItem('Top K', preset.params.top_k),
    fitItem('Top P', preset.params.top_p),
    fitItem('Min P', preset.params.min_p),
    fitItem('Repeat penalty', preset.params.repeat_penalty),
  ].filter(Boolean).join('');
  setModelNote('sampling', `
    <div class="fit-summary">
      <div class="fit-status"><span class="badge ok">Applied</span><strong>${escapeHtml(preset.label)}</strong></div>
      <p>${escapeHtml(preset.description)}</p>
      <div class="fit-groups"><section><h4>Sampling</h4><ul>${paramItems}</ul></section></div>
      ${rationale ? `<details class="fit-details"><summary>Why these values</summary><ul>${rationale}</ul></details>` : ''}
    </div>`);
  toast(`Applied ${preset.label} sampling`);
}

async function runFitTest() {
  const mode = selectedMode();
  if (!mode) return;
  const trigger = $('#fit-button');
  setSelectedProfileMode(mode);
  const overrides = saveCurrentOverrides();
  const target = Number($('#param-fit-target').value || 1024);
  setModelNote('fit', 'Running fit test. This may take a moment...');
  await withBusy(trigger, async () => {
    try {
      const result = await api('/api/profiles/fit', {
        method: 'POST',
        body: JSON.stringify({ mode, overrides, target_mib: target, timeout_seconds: 180 }),
      });
      const applied = applyFitResultParams(result);
      const suggestions = result.suggestions || {};
      setModelNote('fit', renderFitSummary(result, applied));
      renderTpsEstimate(result.speed_estimate);
      scheduleTpsEstimate(80);
      showLogPreview(parsedFitAccepted(suggestions)
        ? fitSummaryText(applied, suggestions, result.speed_estimate)
        : (result.command_line || result.stdout || 'Fit test completed.'));
      toast('Fit test complete');
    } catch (error) {
      setModelNote('fit', `<strong>Fit test failed</strong>\n${escapeHtml(error.message)}`);
      toast(`Fit test failed: ${error.message}`);
    }
  });
}

function renderBenchmarkSummary(result) {
  const benchmark = result.benchmark || {};
  const preview = result.response_preview ? `\n\n${escapeHtml(result.response_preview)}` : '';
  return `
    <div class="fit-summary">
      <div class="fit-status">
        <span class="badge ok">Measured</span>
        <strong>Benchmark complete</strong>
      </div>
      <div class="fit-groups">
        <section>
          <h4>Decode speed</h4>
          <ul>
            ${fitItem('Tokens/sec', benchmark.tokens_per_second)}
            ${fitItem('Generated tokens', benchmark.completion_tokens)}
            ${fitItem('Elapsed', benchmark.elapsed_seconds, ' sec')}
          </ul>
        </section>
        <section>
          <h4>Request</h4>
          <ul>
            ${fitItem('Prompt tokens', benchmark.prompt_tokens)}
            ${fitItem('Total tokens', benchmark.total_tokens)}
            ${fitItem('Chars/sec', benchmark.chars_per_second)}
          </ul>
        </section>
      </div>
      <details class="fit-details"><summary>Response preview</summary><code>${preview || 'No preview returned.'}</code></details>
    </div>
  `;
}

function renderBenchmarkHistory() {
  const container = $('#benchmark-history');
  const list = $('#benchmark-history-list');
  if (!container || !list) return;

  const all = state.benchmarks || [];
  const currentMode = selectedMode();
  const recent = all.slice(-5).reverse(); // newest first

  if (!recent.length) {
    container.style.display = 'none';
    return;
  }
  container.style.display = '';

  let html = '<table><thead><tr><th>When</th><th>Mode</th><th>t/s</th><th>tok</th><th>Action</th></tr></thead><tbody>';
  recent.forEach((b, i) => {
    const bm = b.benchmark || b;
    const when = b.timestamp ? new Date(b.timestamp).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'}) : '–';
    const mode = b.mode || '–';
    const tps = bm.tokens_per_second ? bm.tokens_per_second.toFixed(1) : '–';
    const toks = bm.completion_tokens || bm.total_tokens || '–';
    const isCurrent = currentMode && mode === currentMode;
    const cls = isCurrent ? 'current' : '';
    html += `<tr class="${cls}"><td>${escapeHtml(when)}</td><td>${escapeHtml(mode)}</td><td>${tps}</td><td>${toks}</td>`;
    html += `<td><button class="mini-button" data-bench-idx="${all.length - 1 - i}">Use</button></td></tr>`;
  });
  html += '</tbody></table>';
  list.innerHTML = html;

  list.querySelectorAll('button[data-bench-idx]').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.benchIdx);
      const entry = all[idx];
      if (entry && entry.mode) {
        setSelectedProfileMode(entry.mode);
        renderParameters();
        renderProfiles();
        toast('Loaded params from benchmark history (approximate)');
      }
    });
  });
}

async function sendTestPrompt() {
  const mode = selectedMode();
  if (!mode) {
    toast('Select a profile first');
    return;
  }
  if (!serverRunningForMode(mode)) {
    toast(`Start the server for "${profileLabel(mode)}" first`);
    return;
  }
  const input = $('#test-prompt-input');
  const prompt = (input.value || '').trim();
  if (!prompt) {
    toast('Enter a message to send');
    return;
  }

  // Maintain history for this mode
  if (!state.chatHistory[mode]) state.chatHistory[mode] = [];
  const history = state.chatHistory[mode];

  // Append user message. One entry appended, not a whole transcript rebuilt:
  // the log is a live region, so only the new line should be announced.
  history.push({ role: 'user', content: prompt });
  persistChatHistory();
  appendChatEntry(mode, { role: 'user', content: prompt });

  input.value = '';

  await withBusy($('#test-prompt-send'), async () => {
    try {
      // Send full history so backend can do proper multi-turn
      const result = await api('/api/servers/test-prompt', {
        method: 'POST',
        body: JSON.stringify({
          mode,
          messages: history,           // full conversation
          max_tokens: 512,
        }),
      });

      if (result.success && result.reply) {
        history.push({ role: 'assistant', content: result.reply });
        persistChatHistory();
        appendChatEntry(mode, { role: 'assistant', content: result.reply });

        // Show last-turn stats
        const meta = $('#test-prompt-meta');
        if (meta) {
          meta.hidden = false;
          meta.textContent = `${result.tokens_per_second || '?'} tok/s · ${result.completion_tokens || '?'} tokens · ${result.elapsed_seconds || '?'}s`;
        }
      } else {
        rollbackChatSend(mode, history, input, prompt);
        toast(result.error || 'Chat failed');
      }
    } catch (error) {
      rollbackChatSend(mode, history, input, prompt);
      toast(`Chat error: ${error.message}`);
    }
  });
}

// A failed send must not eat what the user typed: drop the optimistic history
// entry and put the message back in the box, ready to retry. If they already
// started typing something else while waiting, that draft wins.
function rollbackChatSend(mode, history, input, prompt) {
  history.pop();
  persistChatHistory();
  const container = $('#chat-log');
  // Drop just the optimistic line rather than repainting (and re-announcing)
  // the transcript around it.
  container?.querySelector('.chat-entry:last-child')?.remove();
  if (!(state.chatHistory[mode] || []).length) renderChatLog(mode);
  if (input && !input.value.trim()) {
    input.value = prompt;
    input.focus();
  }
}

// Transcript entries are terminal lines, not bubbles: a role gutter, the text
// in mono, a hairline between turns. Markup is built once here so the
// incremental and full-rebuild paths cannot drift apart.
function chatEntryHtml(msg) {
  const isUser = msg.role === 'user';
  return `
    <div class="chat-entry ${isUser ? 'user' : 'assistant'}">
      <span class="chat-role">${isUser ? 'you' : 'model'}<span aria-hidden="true"> ›</span></span>
      <span class="chat-text">${escapeHtml(msg.content)}</span>
    </div>`;
}

function appendChatEntry(mode, msg) {
  const container = $('#chat-log');
  if (!container) return;
  if (!container.querySelector('.chat-entry')) container.innerHTML = '';
  container.insertAdjacentHTML('beforeend', chatEntryHtml(msg));
  container.scrollTop = container.scrollHeight;
}

// Full rebuild — only when the transcript being shown changes wholesale
// (profile switch, Clear). The live region is muted across the swap so a
// switch does not read the entire history back out.
function renderChatLog(mode) {
  const container = $('#chat-log');
  if (!container) return;

  const history = state.chatHistory[mode] || [];
  const liveServer = serverRunningForMode(mode);
  container.setAttribute('aria-live', 'off');
  container.innerHTML = history.length
    ? history.map(chatEntryHtml).join('')
    : emptyStateHtml(chatEmptyCopy(!!liveServer, liveServer));
  container.scrollTop = container.scrollHeight;
  window.requestAnimationFrame(() => container.setAttribute('aria-live', 'polite'));
}

function clearChat() {
  const mode = selectedMode();
  if (!mode) return;
  state.chatHistory[mode] = [];
  persistChatHistory();
  renderChatLog(mode);
  const meta = $('#test-prompt-meta');
  if (meta) meta.hidden = true;
}

async function runBenchmark() {
  const mode = selectedMode();
  if (!mode) return;
  setSelectedProfileMode(mode);
  const profile = getSelectedProfile();
  if (!profile?.launchable) {
    toast('Choose a launchable profile before benchmarking');
    return;
  }
  const confirmed = await confirmAction({
    title: 'Run benchmark',
    message: `Benchmark "${profileLabel(mode)}" with the current parameters? This may restart the tracked server for this profile.`,
    confirmLabel: 'Benchmark',
    confirmKind: 'primary',
  });
  if (!confirmed) return;
  const trigger = $('#benchmark-button');
  const overrides = saveCurrentOverrides();
  const requested = Number($('#param-predict').value || 128);
  const completionTokens = requested > 0 ? Math.min(requested, 512) : 128;
  setModelNote('benchmark', 'Running benchmark with the current parameters...');
  await withBusy(trigger, async () => {
    try {
      const result = await api('/api/benchmarks/run', {
        method: 'POST',
        body: JSON.stringify({
          mode,
          overrides,
          completion_tokens: completionTokens,
          restart: true,
          stop_after: false,
          ready_timeout_seconds: 90,
        }),
      });
      setModelNote('benchmark', renderBenchmarkSummary(result));
      renderMeasuredTps(result.benchmark.tokens_per_second, result.benchmark.elapsed_seconds);
      showLogPreview([
        `Benchmark: ${result.benchmark.tokens_per_second} tok/s`,
        `Elapsed: ${result.benchmark.elapsed_seconds}s`,
        `Endpoint: ${result.benchmark.endpoint}`,
      ].join('\n'));
      toast(`Benchmark: ${result.benchmark.tokens_per_second} tok/s`);
      await refresh();
      renderBenchmarkHistory();
      const currentKey = estimateKey(selectedMode() || '', collectOverrides());
      if (currentKey === state.lastBenchmarkKey && state.measuredTps) {
        renderMeasuredTps(state.measuredTps, state.measuredElapsed);
      }
    } catch (error) {
      setModelNote('benchmark', `<strong>Benchmark failed</strong>\n${escapeHtml(error.message)}`);
      toast(`Benchmark failed: ${error.message}`);
    }
  });
}

async function fetchHFInfo() {
  const profile = getSelectedProfile();
  if (!profile) return;
  const trigger = $('#hf-info-button');
  setModelNote('hf', 'Fetching Hugging Face metadata...');
  await withBusy(trigger, async () => {
    try {
      const result = await api('/api/models/hf-info', {
        method: 'POST',
        body: JSON.stringify({
          name: profile.model?.name || profile.name,
          path: profile.model?.path || '',
        }),
      });
      const lines = [
        `<strong>${escapeHtml(result.model_id || 'Hugging Face model')}</strong>`,
        result.url ? escapeHtml(result.url) : '',
        result.summary ? escapeHtml(result.summary) : 'No model-card summary found.',
        '',
        `Downloads: ${escapeHtml(result.downloads ?? '-')}`,
        `Likes: ${escapeHtml(result.likes ?? '-')}`,
        `Tags: ${escapeHtml((result.tags || []).slice(0, 8).join(', ') || '-')}`,
      ].filter(Boolean).join('\n');
      setModelNote('hf', lines);
      toast('HF info loaded');
    } catch (error) {
      setModelNote('hf', `<strong>HF lookup failed</strong>\n${escapeHtml(error.message)}`);
      toast(`HF lookup failed: ${error.message}`);
    }
  });
}

function dirname(path) {
  const idx = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
  return idx > 0 ? path.slice(0, idx) : '';
}

async function checkModelUpdate() {
  const profile = getSelectedProfile();
  if (!profile) return;
  const path = profile.model?.path || '';
  const trigger = $('#hf-update-button');
  setModelNote('hf', 'Checking Hugging Face for a newer copy...');
  await withBusy(trigger, async () => {
    try {
      const result = await api('/api/models/hf-update-check', {
        method: 'POST',
        body: JSON.stringify({ name: profile.model?.name || profile.name, path }),
      });
      const lines = [
        `<strong>${escapeHtml(result.model_id || 'Hugging Face model')}</strong>`,
        result.url ? escapeHtml(result.url) : '',
        result.confident ? '' : 'Matched by search — verify this is the right repo before downloading.',
        result.update_available ? `⚠ Update available — ${escapeHtml(result.reason)}` : `✓ ${escapeHtml(result.reason)}`,
        result.last_modified ? `Repo last modified: ${escapeHtml(result.last_modified)}` : '',
      ];
      // Offer a targeted re-download only when we found the exact file remotely
      // and know where the local copy lives.
      const dest = dirname(path);
      if (result.update_available && result.remote_file?.rfilename && dest) {
        lines.push(
          `<button class="mini-button" type="button" data-action="download-model"`
          + ` data-repo="${escapeHtml(result.model_id)}"`
          + ` data-file="${escapeHtml(result.remote_file.rfilename)}"`
          + ` data-dest="${escapeHtml(dest)}">Download latest into ${escapeHtml(dest)}</button>`,
        );
      }
      setModelNote('hf', lines.filter(Boolean).join('\n'));
      toast(result.update_available ? 'HF update available' : 'Model is up to date');
    } catch (error) {
      setModelNote('hf', `<strong>HF update check failed</strong>\n${escapeHtml(error.message)}`);
      toast(`HF update check failed: ${error.message}`);
    }
  });
}

function listedHfFiles(data) {
  const raw = Array.isArray(data?.files) ? data.files : [];
  const names = raw.map((item) => String(item || '').replace(/\\/g, '/').trim()).filter(Boolean);
  const gguf = names.filter((name) => /\.gguf$/i.test(name));
  return gguf.length ? gguf : names;
}

async function searchHfBrowser() {
  const input = $('#hf-search-input');
  const q = (input.value || '').trim();
  const resEl = $('#hf-browser-results');
  if (!q || !resEl) return;
  resEl.innerHTML = '<div class="loading">Fetching info…</div>';
  try {
    const data = await api('/api/models/hf-info', {
      method: 'POST',
      body: JSON.stringify({ repo_id: q }),
    });
    if (!data.success) {
      resEl.innerHTML = emptyStateHtml({
        title: 'No repo found',
        body: data.error || 'Hugging Face did not return a model card for that id.',
      });
      return;
    }
    const files = listedHfFiles(data);
    let html = `<strong>${escapeHtml(data.model_id || q)}</strong><br>`;
    html += `Downloads: ${data.downloads || '–'} · Likes: ${data.likes || '–'}<br>`;
    if (data.summary) html += `<small>${escapeHtml(String(data.summary).slice(0, 120))}</small><br>`;
    if (!files.length) {
      html += emptyStateHtml({
        title: 'No downloadable files listed',
        body: 'This repo did not publish filenames. Open it on Hugging Face instead of guessing a quant.',
      });
    } else {
      html += '<div class="hf-file-list">';
      files.slice(0, 40).forEach((file) => {
        html += `<div class="hf-file-row"><span>${escapeHtml(file)}</span> <button class="mini-button" type="button" data-hf-repo="${escapeHtml(data.model_id || q)}" data-hf-file="${escapeHtml(file)}">Download</button></div>`;
      });
      html += '</div>';
    }
    resEl.innerHTML = html;

    resEl.querySelectorAll('button[data-hf-repo]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const dest = (state.inventory?.scan_roots || [])[0] || '';
        if (!dest) {
          toast('Add a model folder in Settings before downloading.');
          openSettings({ focus: 'model-dirs' });
          return;
        }
        await downloadModelUpdate(btn.dataset.hfRepo, btn.dataset.hfFile, dest, btn);
      });
    });
  } catch (err) {
    resEl.innerHTML = emptyStateHtml({
      title: 'Hugging Face lookup failed',
      body: err.message || 'The request did not complete.',
    });
  }
}

async function downloadModelUpdate(repo, file, dest, trigger) {
  if (!repo || !file || !dest) {
    toast('Need a repo, filename, and destination folder.');
    return;
  }
  const confirmed = await confirmAction({
    title: 'Download model file',
    message: `Write ${file} from ${repo} into ${dest}. If that filename is already there, it will be replaced.`,
    confirmLabel: 'Download',
  });
  if (!confirmed) return;
  await withBusy(trigger, async () => {
    try {
      const result = await api('/api/models/hf-download', {
        method: 'POST',
        body: JSON.stringify({ repo_id: repo, filename: file, dest_dir: dest }),
      });
      toast(result.message || 'Download complete');
    } catch (error) {
      toast(`Download failed: ${error.message}`);
    }
  });
}

async function stopTracked(serverId, trigger) {
  const tracked = (state.servers || []).find((server) => server.id === serverId);
  const label = tracked?.mode ? `"${profileLabel(tracked.mode)}"` : 'this tracked server';
  const confirmed = await confirmAction({
    title: 'Stop server',
    message: `Stop the server running ${label}?`,
    confirmLabel: 'Stop',
    confirmKind: 'danger',
  });
  if (!confirmed) return;
  await withBusy(trigger, async () => {
    try {
      await api('/api/servers/stop', {
        method: 'POST',
        body: JSON.stringify({ server_id: serverId }),
      });
      toast(releasedToast(tracked, tracked?.mode ? profileLabel(tracked.mode) : 'server'));
      await refresh();
      renderProfiles();
      renderLaunchLock();
    } catch (error) {
      toast(`Stop failed: ${error.message}`);
    }
  });
}

async function restartTracked(serverId, trigger) {
  // M2.2: Restart re-uses the tracked mode to launch again (for crashed servers mainly).
  const server = (state.servers || []).find((s) => s.id === serverId);
  const mode = server && server.mode;
  if (!mode) {
    toast('No mode available to restart');
    return;
  }
  const confirmed = await confirmAction({
    title: 'Restart server',
    message: `Restart "${profileLabel(mode)}"? This will launch a fresh instance.`,
    confirmLabel: 'Restart',
    confirmKind: 'primary',
  });
  if (!confirmed) return;
  setLaunchWaiting(true);
  await withBusy(trigger, async () => {
    try {
      const result = await api('/api/servers/start', {
        method: 'POST',
        body: JSON.stringify({ mode, wait_ready: true, ready_timeout_seconds: 45 }),
      });
      toast(listeningToast(result.server, profileLabel(mode)), {
        label: 'Open Chat',
        onClick: () => showPanel('chat'),
      });
      await refresh();
      renderProfiles();
      renderLaunchLock({ justLocked: true });
    } catch (error) {
      toast(`Restart failed: ${error.message}`);
    } finally {
      setLaunchWaiting(false);
    }
  });
}

async function stopProfileByMode(mode, trigger) {
  if (!mode) {
    toast('No profile mode specified');
    return;
  }
  const tracked = (state.servers || []).find((server) => server.mode === mode && server.running);
  const endpoint = serverEndpoint(tracked);
  const confirmed = await confirmAction({
    title: 'Stop server',
    message: endpoint
      ? `Stop the server listening on ${endpoint}?`
      : `Stop the running server for "${profileLabel(mode)}"?`,
    confirmLabel: 'Stop',
    confirmKind: 'danger',
  });
  if (!confirmed) return;
  await withBusy(trigger, async () => {
    try {
      await api('/api/servers/stop', {
        method: 'POST',
        body: JSON.stringify({ mode }),
      });
      toast(releasedToast(tracked, profileLabel(mode)));
      await refresh();
      renderProfiles();
      renderLaunchLock();
    } catch (error) {
      toast(`Stop failed: ${error.message}`);
    }
  });
}

async function loadLogs(serverId, trigger, options = {}) {
  await withBusy(trigger, async () => {
    try {
      const result = await api(`/api/servers/${encodeURIComponent(serverId)}/logs?lines=160`);
      state.selectedServerId = serverId;
      showLogPreview(result.stderr || 'No log output yet.', result.stdout || '');
      if (!options.silent) toast('Logs loaded');
    } catch (error) {
      toast(`Logs failed: ${error.message}`);
    }
  });
}

async function purgeServers(onlyNonRunning = true, trigger = null, clearAll = false) {
  const label = clearAll ? 'Clear all server history' : (onlyNonRunning ? 'Purge stopped/crashed servers' : 'Purge servers');
  const ok = await confirmAction({ title: label, message: clearAll ? 'This will remove every tracked server entry (running or not). Continue?' : 'Remove non-running server entries from history?', confirmLabel: 'Purge', confirmKind: clearAll ? 'danger' : 'primary' });
  if (!ok) return;
  await withBusy(trigger, async () => {
    try {
      const params = clearAll ? { all: 'true' } : { only_non_running: onlyNonRunning ? 'true' : 'false' };
      const qs = new URLSearchParams(params).toString();
      const res = await api(`/api/servers/purge?${qs}`, { method: 'POST' });
      toast(res.message || 'Server history purged');
      await refresh();
    } catch (error) {
      toast(`Purge failed: ${error.message}`);
    }
  });
}

const PANEL_COLLAPSE_KEY = 'lcc-collapsed-panels';
const DEFAULT_COLLAPSED_PANELS = [];

function loadCollapsedPanels() {
  try {
    const raw = JSON.parse(localStorage.getItem(PANEL_COLLAPSE_KEY));
    if (Array.isArray(raw)) return new Set(raw);
  } catch (error) {
    /* fall through to defaults */
  }
  return new Set(DEFAULT_COLLAPSED_PANELS);
}

const DESTINATIONS = {
  console: { title: 'Console', summary: 'Selected profile, memory fit, and Start.' },
  inventory: { title: 'Inventory', summary: 'Runtimes, profiles, and local models.' },
  tools: { title: 'Tools', summary: 'Hugging Face, portability, and Settings.' },
};

const SESSION_VIEWS = ['stage', 'chat', 'logs', 'server'];

const PANEL_ROUTE = {
  console: { dest: 'console', session: 'stage' },
  stage: { dest: 'console', session: 'stage' },
  parameters: { dest: 'console', session: 'stage' },
  chat: { dest: 'console', session: 'chat' },
  logs: { dest: 'console', session: 'logs' },
  servers: { dest: 'console', session: 'server' },
  server: { dest: 'console', session: 'server' },
  inventory: { dest: 'inventory' },
  runtimes: { dest: 'inventory' },
  profiles: { dest: 'inventory' },
  models: { dest: 'inventory' },
  tools: { dest: 'tools' },
  'hf-tools': { dest: 'tools' },
  portability: { dest: 'tools' },
};

function showDestination(dest, session) {
  const nextDest = DESTINATIONS[dest] ? dest : 'console';
  const nextSession = SESSION_VIEWS.includes(session) ? session : 'stage';
  const main = $('.main');
  if (main) {
    main.dataset.destination = nextDest;
    main.dataset.session = nextSession;
  }
  $$('.destination').forEach((el) => {
    el.hidden = el.dataset.destination !== nextDest;
  });
  $$('.nav-item[data-destination]').forEach((el) => {
    const on = el.dataset.destination === nextDest;
    el.classList.toggle('active', on);
    if (on) el.setAttribute('aria-current', 'page');
    else el.removeAttribute('aria-current');
  });
  $$('.session-tab').forEach((el) => {
    const on = el.dataset.session === nextSession;
    el.classList.toggle('active', on);
    el.setAttribute('aria-selected', String(on));
  });
  $$('.session-view').forEach((el) => {
    el.hidden = el.dataset.session !== nextSession;
  });
  const heading = $('#topbar-heading');
  if (heading) heading.textContent = DESTINATIONS[nextDest].title;
  const summary = $('#summary-line');
  if (summary) {
    if (nextDest === 'console') {
      summary.textContent = consoleSummaryLine();
    } else {
      summary.textContent = DESTINATIONS[nextDest].summary;
    }
  }
  try {
    localStorage.setItem('lcc-destination', nextDest);
    localStorage.setItem('lcc-session', nextSession);
  } catch { /* private mode */ }
  const hash = nextDest === 'console' && nextSession !== 'stage'
    ? (nextSession === 'server' ? 'servers' : nextSession)
    : nextDest;
  if (location.hash !== `#${hash}`) {
    history.replaceState(null, '', `#${hash}`);
  }
  if (nextSession === 'logs' && state.selectedServerId) {
    loadLogs(state.selectedServerId, null, { silent: true });
  }
}

function showPanel(id) {
  const mapped = PANEL_ROUTE[id] || PANEL_ROUTE.console;
  showDestination(mapped.dest, mapped.session);
}

function applyHashRoute() {
  const id = (location.hash || '').replace(/^#/, '');
  if (id && PANEL_ROUTE[id]) {
    showPanel(id);
    return;
  }
  let dest = 'console';
  let session = 'stage';
  try {
    dest = localStorage.getItem('lcc-destination') || dest;
    session = localStorage.getItem('lcc-session') || session;
  } catch { /* ignore */ }
  showDestination(dest, session);
}

// Open the destination that owns this panel, then uncollapse it if it still
// uses the inventory accordion.
function revealPanel(id) {
  showPanel(id);
  const panel = document.getElementById(id);
  if (!panel) return;
  panel.classList.remove('collapsed');
  const toggle = panel.querySelector('.panel-toggle');
  if (toggle) toggle.setAttribute('aria-expanded', 'true');
  try {
    const raw = JSON.parse(localStorage.getItem(PANEL_COLLAPSE_KEY));
    const next = new Set(Array.isArray(raw) ? raw : DEFAULT_COLLAPSED_PANELS);
    next.delete(id);
    localStorage.setItem(PANEL_COLLAPSE_KEY, JSON.stringify([...next]));
  } catch { /* ignore persist failures; the panel is already open */ }
}

function enhancePanels() {
  const collapsed = loadCollapsedPanels();
  const saveState = () => localStorage.setItem(PANEL_COLLAPSE_KEY, JSON.stringify([...collapsed]));

  $$('.panel').forEach((panel) => {
    if (panel.closest('.session-view, #destination-tools')) return;
    const heading = panel.querySelector(':scope > .panel-heading');
    if (!heading || panel.querySelector(':scope > .panel-body')) return;

    const inner = document.createElement('div');
    inner.className = 'panel-body-inner';
    let node = heading.nextSibling;
    while (node) {
      const next = node.nextSibling;
      inner.appendChild(node);
      node = next;
    }
    const body = document.createElement('div');
    body.className = 'panel-body';
    body.appendChild(inner);
    panel.appendChild(body);

    const id = panel.id;
    const titleZone = heading.querySelector(':scope > div');
    const headingName = heading.querySelector('h3')?.textContent.trim() || 'section';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'panel-toggle';
    toggle.innerHTML = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    heading.appendChild(toggle);

    const apply = (isCollapsed, persist) => {
      panel.classList.toggle('collapsed', isCollapsed);
      toggle.setAttribute('aria-expanded', String(!isCollapsed));
      toggle.setAttribute('aria-label', `${isCollapsed ? 'Expand' : 'Collapse'} ${headingName}`);
      if (persist) {
        if (isCollapsed) collapsed.add(id);
        else collapsed.delete(id);
        saveState();
      }
    };
    apply(collapsed.has(id), false);

    const flip = () => apply(!panel.classList.contains('collapsed'), true);
    toggle.addEventListener('click', (event) => { event.stopPropagation(); flip(); });
    if (titleZone) {
      titleZone.classList.add('panel-title-toggle');
      titleZone.addEventListener('click', flip);
    }
  });
}

function enhanceSidebar() {
  const shell = $('.app-shell');
  const collapsed = localStorage.getItem('lcc-sidebar-collapsed') === '1';
  shell.classList.toggle('sidebar-collapsed', collapsed);
  $$('.nav-item').forEach((item) => {
    const label = item.querySelector('span:last-child');
    if (label && !item.title) item.title = label.textContent.trim();
  });
  const toggle = $('#sidebar-toggle');
  const setToggleLabel = (collapsed) => {
    if (!toggle) return;
    toggle.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    toggle.setAttribute('title', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    toggle.setAttribute('aria-expanded', String(!collapsed));
  };
  setToggleLabel(collapsed);
  toggle.addEventListener('click', () => {
    const next = !shell.classList.contains('sidebar-collapsed');
    shell.classList.toggle('sidebar-collapsed', next);
    localStorage.setItem('lcc-sidebar-collapsed', next ? '1' : '0');
    setToggleLabel(next);
    // Expanding reveals a widget that was sampling but not painting: draw the
    // recorded history immediately instead of waiting out the poll interval.
    if (!next) pollLiveHardware();
  });
}

function syncSearchInputs(value) {
  const input = $('#search-input');
  if (input && input.value !== value) input.value = value;
}

function persistDisclosure(el, key) {
  if (!el) return;
  try {
    if (localStorage.getItem(key) === '1') el.open = true;
  } catch { /* private mode */ }
  el.addEventListener('toggle', () => {
    try {
      localStorage.setItem(key, el.open ? '1' : '0');
    } catch { /* private mode */ }
  });
}

function wireEvents() {
  applyTheme();
  enhanceTooltips();
  $('#api-copy')?.addEventListener('click', () => {
    const details = $('#api-copy')?.dataset.details;
    if (!details) return;
    navigator.clipboard.writeText(details).then(() => toast('API status copied to clipboard'));
  });
  persistDisclosure($('#param-sampling-disclosure'), 'lcc-params-sampling');
  persistDisclosure($('#param-advanced-disclosure'), 'lcc-params-advanced');
  enhancePanels();
  enhanceSidebar();
  wireToolsMenu();
  // Enable layout transitions only after the initial collapsed state is painted,
  // so panels and the sidebar don't animate from open→closed on first load.
  requestAnimationFrame(() => $('.app-shell').classList.add('anim-ready'));
  $('#refresh-button').addEventListener('click', refresh);
  $('#check-updates-button').addEventListener('click', (event) => refreshRuntimeUpdates(event.currentTarget));
  $('#settings-button').addEventListener('click', openSettings);
  $('#settings-nav-button')?.addEventListener('click', openSettings);
  $('#tools-open-settings')?.addEventListener('click', openSettings);
  $('#settings-close-button').addEventListener('click', closeSettings);
  $('#settings-cancel-button').addEventListener('click', closeSettings);
  $('#settings-modal').addEventListener('click', (event) => {
    if (event.target.id === 'settings-modal') closeSettings();
  });
  $('#settings-form').addEventListener('submit', saveSettings);
  $('#settings-use-scan-roots').addEventListener('click', () => {
    $('#settings-model-dirs').value = listToLines(state.inventory?.scan_roots || []);
  });
  $('#settings-use-runtime-roots').addEventListener('click', () => {
    $('#settings-runtime-dirs').value = listToLines(detectedRuntimeRoots());
  });
  $('#settings-reset-defaults')?.addEventListener('click', () => {
    // Reset the form fields to sensible portable defaults (does not save until user clicks Save)
    $('#settings-model-dirs').value = '';
    $('#settings-runtime-dirs').value = '';
    $('#settings-llama-server').value = '';
    $('#settings-llama-fit').value = '';
    $('#settings-default-host').value = '127.0.0.1';
    $('#settings-default-port').value = '8080';
    $('#settings-default-backend').value = 'llama.cpp';
    $('#settings-update-channel').value = 'stable';
    $('#settings-server-history-limit').value = '5';
    $('#settings-extra-args').value = '';
    const a2 = $('#settings-auto-scan'); if (a2) a2.checked = true;
    toast('Form reset to defaults (click Save to apply)');
  });
  $('#settings-export-button')?.addEventListener('click', async (e) => {
    await exportPortableConfig(e.currentTarget);
  });
  $('#portability-export')?.addEventListener('click', async (e) => {
    await exportPortableConfig(e.currentTarget);
  });
  // Palette backdrop close
  const palBack = $('#command-palette');
  if (palBack) palBack.addEventListener('click', (e) => { if (e.target.id === 'command-palette') hideCommandPalette(); });
  $('#theme-button').addEventListener('click', cycleTheme);
  // While following the system, an OS-level switch has to land immediately.
  darkMediaQuery.addEventListener('change', () => {
    if (state.theme === 'system') applyTheme();
  });
  $('#search-input').addEventListener('input', (event) => {
    state.query = event.target.value;
    syncSearchInputs(state.query);
    renderProfiles();
    renderModels();
  });
  $('#profile-filter-input')?.addEventListener('input', (event) => {
    state.query = event.target.value;
    syncSearchInputs(state.query);
    renderProfiles();
    renderModels();
  });
  $('#profile-model-filter')?.addEventListener('change', (event) => {
    state.profileModelFilter = event.target.value || 'all';
    renderProfiles();
  });
  $('#hide-unavailable-profiles')?.addEventListener('change', (event) => {
    state.hideUnavailableProfiles = event.target.checked;
    localStorage.setItem('lcc-hide-unavailable-profiles', state.hideUnavailableProfiles ? '1' : '0');
    renderProfiles();
  });
  const hideNotInstalled = $('#hide-not-installed-runtimes');
  if (hideNotInstalled) {
    hideNotInstalled.checked = !!state.hideNotInstalledRuntimes;
    hideNotInstalled.addEventListener('change', (event) => {
      state.hideNotInstalledRuntimes = event.target.checked;
      localStorage.setItem('lcc-hide-not-installed-runtimes', state.hideNotInstalledRuntimes ? '1' : '0');
      renderRuntimes();
    });
  }
  $('#new-profile-button')?.addEventListener('click', (event) => createNewProfile(event.currentTarget));
  $('#profile-menu-button')?.addEventListener('click', () => {
    const mode = state.selectedProfileMode;
    if (!mode) {
      toast('Select a profile row first');
      return;
    }
    const profile = state.profiles.find((p) => p.mode === mode);
    if (!profile) {
      toast('Selected profile not found');
      return;
    }
    if (!profile.launchable) {
      toast('Selected profile is not launchable; nothing to save');
      return;
    }
    saveProfileAsCopy(profile);
  });
  $('#profiles-table').addEventListener('click', (event) => {
    const row = event.target.closest('tr.profile-row');
    if (!row) return;
    if (event.target.closest('button')) return;
    const mode = row.dataset.profileMode;
    if (!mode || !setSelectedProfileMode(mode)) return;
    renderParameters();
    renderProfiles();
  });
  $('#profiles-table').addEventListener('keydown', (event) => {
    const row = event.target.closest('tr.profile-row');
    if (!row || event.target.closest('button')) return;
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    const mode = row.dataset.profileMode;
    if (!mode || !setSelectedProfileMode(mode)) return;
    renderParameters();
    renderProfiles();
  });
  $('#profiles-table').addEventListener('click', (event) => {
    const toggle = event.target.closest('.group-toggle');
    if (toggle) {
      event.stopPropagation();
      toggleGroup(toggle.dataset.model);
      return;
    }
  });
  document.body.addEventListener('click', (event) => {
    const launchAction = event.target.closest('[data-launch-action]');
    if (launchAction) {
      const act = launchAction.dataset.launchAction;
      if (act === 'copy') {
        const url = serverUrl(serverRunningForMode(selectedMode()));
        if (!url) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(url).then(() => toast(`Copied ${url}`));
        } else {
          toast(url);
        }
      } else if (act === 'chat') {
        showPanel('chat');
      }
      return;
    }
    const emptyAction = event.target.closest('[data-empty-action]');
    if (emptyAction) {
      const act = emptyAction.dataset.emptyAction;
      if (act === 'add-folders') openSettings({ focus: 'model-dirs' });
      else if (act === 'add-runtime-folders') openSettings({ focus: 'runtime-dirs' });
      else if (act === 'clear-filters') clearProfileFilters();
      else if (act === 'goto-models') showPanel('models');
      else if (act === 'goto-inventory') showDestination('inventory');
      else if (act === 'goto-stage') showPanel('parameters');
      else if (act === 'show-all-runtimes') {
        state.hideNotInstalledRuntimes = false;
        localStorage.setItem('lcc-hide-not-installed-runtimes', '0');
        const toggle = $('#hide-not-installed-runtimes');
        if (toggle) toggle.checked = false;
        renderRuntimes();
      }
      return;
    }
    // Server selection (clicking the card itself, not action buttons inside)
    const serverCard = event.target.closest('.server-item');
    if (serverCard && !event.target.closest('button')) {
      const sid = serverCard.dataset.serverId;
      if (sid) {
        state.selectedServerId = sid;
        const server = (state.servers || []).find(s => s.id === sid);
        // Selecting a server selects its profile too, so the chat transcript,
        // the parameter form and the highlighted row all describe one thing.
        if (server?.mode && state.profiles.some((profile) => profile.mode === server.mode)) {
          if (setSelectedProfileMode(server.mode)) {
            renderParameters();
            renderProfiles();
          }
        }
        $$('.server-item').forEach((el) => {
          const on = el.dataset.serverId === sid;
          el.classList.toggle('selected', on);
          el.setAttribute('aria-selected', String(on));
        });
        if ($('.main')?.dataset.session === 'logs') {
          loadLogs(sid, null, { silent: true });
        }
      }
    }

    const target = event.target.closest('button');
    if (!target) return;
    const { action, mode, serverId, runtime, repo, file, dest } = target.dataset;
    if (mode && state.profiles.some((profile) => profile.mode === mode)) {
      if (setSelectedProfileMode(mode)) renderParameters();
    }
    if (action === 'download-model') downloadModelUpdate(repo, file, dest, target);
    else if (action === 'toggle-runtimes') {
      state.showAllRuntimes = !state.showAllRuntimes;
      renderRuntimes();
    }
    else if (action === 'recheck-runtime') recheckRuntime(runtime, target);
    else if (action === 'prepare') prepareProfile(mode, target);
    else if (action === 'start') startProfile(mode, target);
    else if (action === 'logs') loadLogs(serverId, target);
    else if (action === 'restart') {
      if (serverId) restartTracked(serverId, target);
    }
    else if (action === 'stop') {
      if (serverId) stopTracked(serverId, target);
      else if (mode) stopProfileByMode(mode, target);
    }
    else if (action === 'profile-menu') openProfileMenu(target, mode);
    else if (action === 'rename') {
      const profile = state.profiles.find((p) => p.mode === mode);
      if (profile) saveProfileName(mode, profile.name || profile.mode);
    }
  });
  $('#server-box')?.addEventListener('keydown', (event) => {
    const card = event.target.closest('.server-item');
    if (!card || event.target.closest('button')) return;
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    card.click();
  });
  $('#open-logs-button').addEventListener('click', () => {
    const serverId = state.selectedServerId || state.servers[0]?.id;
    if (serverId) loadLogs(serverId);
    else toast('No tracked server to open logs for');
  });
  $('#servers-purge-stopped')?.addEventListener('click', (e) => purgeServers(true, e.currentTarget));
  $('#servers-clear-history')?.addEventListener('click', (e) => purgeServers(false, e.currentTarget, true));
  $('#param-profile').addEventListener('change', (event) => {
    setSelectedProfileMode(event.target.value);
    renderParameters();
    renderProfiles();
  });
  $('#reset-params-button').addEventListener('click', () => {
    const mode = selectedMode();
    clearParamOverrides(mode);
    renderParameters();
    toast('Parameters reset to the saved profile');
  });
  $('#prepare-selected-button').addEventListener('click', (event) => prepareProfile(selectedMode(), event.currentTarget));
  $('#start-selected-button')?.addEventListener('click', (event) => startProfile(selectedMode(), event.currentTarget));
  $('#stop-selected-button')?.addEventListener('click', (event) => stopProfileByMode(selectedMode(), event.currentTarget));
  $('#smart-fit-button').addEventListener('click', runAutoTune);
  $('#model-info-box').addEventListener('click', (event) => {
    const button = event.target.closest('[data-tune-index]');
    if (button) applyTuneSuggestion(Number(button.dataset.tuneIndex));
  });
  $('#sampling-suggest-button').addEventListener('click', applySamplingPreset);
  $('#fit-button').addEventListener('click', runFitTest);
  $('#model-list').addEventListener('click', (event) => {
    const button = event.target.closest('[data-model-action]');
    if (!button) return;
    handleModelAction(button.dataset.modelAction, button.dataset.modelPath, button);
  });
  $('#benchmark-button').addEventListener('click', runBenchmark);
  $('#test-prompt-send').addEventListener('click', sendTestPrompt);
  $('#chat-clear')?.addEventListener('click', clearChat);
  $('#test-prompt-input').addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      sendTestPrompt();
    } else if (event.key === 'Enter' && !event.shiftKey) {
      // allow normal enter to send (like many chats)
      event.preventDefault();
      sendTestPrompt();
    }
  });
  $('#hf-info-button').addEventListener('click', fetchHFInfo);
  // Portability reworked panel actions
  $('#portability-open-settings')?.addEventListener('click', () => openSettings());
  $('#portability-rescan')?.addEventListener('click', async (e) => {
    await withBusy(e.currentTarget, async () => {
      await refresh();
      toast('Rescanned inventory and portability issues');
    });
  });
  $('#hf-update-button').addEventListener('click', checkModelUpdate);
  $('#hf-check-updates-button').addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    const trigger = $('#hf-check-updates-button');
    withBusy(trigger, async () => {
      try {
        const result = await api('/api/hf-cli/check-updates', { method: 'POST' });
        if (result.needs_update) {
          toast('Hugging Face CLI update available');
        } else {
          toast('Hugging Face CLI is up to date');
        }
      } catch (error) {
        toast(`Update check failed: ${error.message}`);
      }
    });
  });
  $('#hf-search-btn')?.addEventListener('click', searchHfBrowser);
  $('#hf-search-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') searchHfBrowser();
  });
  $('#suggest-draft-button').addEventListener('click', suggestDraftModels);
  $('#save-profile-button').addEventListener('click', async () => {
    const mode = selectedMode();
    if (!mode) {
      toast('No profile selected');
      return;
    }
    const profile = state.profiles.find((p) => p.mode === mode);
    try {
      const displayName = profile?.name || mode;
      const result = await promptProfileDetails({
        title: 'Save parameters',
        okLabel: 'Save parameters',
        name: displayName,
        description: profile?.description || '',
        message: `This replaces the saved launch config for "${displayName}" (${mode}) in models.json.`,
      });
      if (!result) return;
      const overrides = collectOverrides();
      const modelPath = profile?.model?.path || '';
      await withBusy($('#save-profile-button'), async () => {
        try {
          const saveResult = await api('/api/profiles/save', {
            method: 'POST',
            body: JSON.stringify({ mode, name: result.name, description: result.description, model_path: modelPath, params: overrides }),
          });
          if (saveResult.success) {
            // The edits are on disk now, so the local draft is no longer "unsaved".
            clearParamOverrides(mode);
            toast(saveResult.message || `Saved "${result.name}"`);
            await refresh();
          } else {
            toast(saveResult.message || 'Save failed');
          }
        } catch (error) {
          toast(`Save failed: ${error.message}`);
        }
      });
    } catch (error) {
      toast(`Save failed: ${error.message}`);
    }
  });
  $('#param-form').addEventListener('change', () => {
    saveCurrentOverrides();
    state.paramPreviewHost = $('#param-host').value.trim() || '127.0.0.1';
    state.paramPreviewPort = numericValue('#param-port') || 8080;
    scheduleTpsEstimate();
    schedulePortCheck();
  });
  $('#param-form').addEventListener('input', () => {
    saveCurrentOverrides();
    state.paramPreviewHost = $('#param-host').value.trim() || '127.0.0.1';
    state.paramPreviewPort = numericValue('#param-port') || 8080;
    scheduleTpsEstimate();
    schedulePortCheck();
  });
  // Click (or Enter/Space) on the dot forces an immediate re-probe, bypassing
  // the debounce. It is exposed as a button, so both paths have to work.
  $('#param-port-status')?.addEventListener('click', () => schedulePortCheck());
  $('#param-port-status')?.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    schedulePortCheck();
  });
  $('#view-all-profiles')?.addEventListener('click', (event) => {
    event.preventDefault();
    clearProfileFilters();
    showPanel('profiles');
  });
  // Preset picker writes into #param-ctx (the source of truth), then resets so it
  // always reads "Presets" and never filters its options by the current value.
  $('#param-ctx-preset').addEventListener('change', (event) => {
    const value = event.target.value;
    event.target.value = '';
    if (!value) return;
    const ctx = $('#param-ctx');
    ctx.value = value;
    ctx.dispatchEvent(new Event('input', { bubbles: true }));
    ctx.dispatchEvent(new Event('change', { bubbles: true }));
  });
  document.addEventListener('keydown', (event) => {
    // AC3: Check Ctrl+Shift+K (more specific) BEFORE plain Ctrl+K so palette trigger works
    if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if (paletteVisible) hideCommandPalette(); else showCommandPalette();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if ($('.main')?.dataset.destination !== 'inventory') showDestination('inventory');
      const search = $('#search-input');
      search?.focus();
      search?.select();
      return;
    }
    if (event.key === 'Escape') {
      if (!$('#settings-modal').hidden) {
        closeSettings();
        return;
      }
      if (paletteVisible) {
        hideCommandPalette();
        return;
      }
    }
    if (!$('#settings-modal').hidden) {
      trapTab(event, $('.settings-dialog'));
    }
  });
  window.addEventListener('resize', hideFloatingTooltip);
  window.addEventListener('scroll', hideFloatingTooltip, true);
  $$('.nav-item[data-destination]').forEach((item) => {
    item.addEventListener('click', (event) => {
      event.preventDefault();
      showDestination(item.dataset.destination, item.dataset.destination === 'console' ? 'stage' : undefined);
    });
  });
  $$('.session-tab').forEach((tab) => {
    tab.addEventListener('click', () => showDestination('console', tab.dataset.session));
  });
  window.addEventListener('hashchange', applyHashRoute);
  applyHashRoute();
}

// ----- Tools disclosure (Parameters panel) ----------------------------------
// Start / Stop / Show command / Save parameters stay on the surface; the six
// occasional tools fold into this menu. The buttons themselves move inside it
// rather than being re-created, so every existing handler and id keeps working.
let toolsMenuKeyHandler = null;
let toolsMenuOutsideHandler = null;

function toolsMenuItems() {
  return $$('#tools-menu .mini-button').filter((button) => !button.disabled);
}

function closeToolsMenu({ restoreFocus = false } = {}) {
  const menu = $('#tools-menu');
  const trigger = $('#tools-menu-button');
  if (!menu || menu.hidden) return;
  menu.hidden = true;
  trigger?.setAttribute('aria-expanded', 'false');
  document.removeEventListener('mousedown', toolsMenuOutsideHandler, true);
  document.removeEventListener('keydown', toolsMenuKeyHandler, true);
  toolsMenuOutsideHandler = null;
  toolsMenuKeyHandler = null;
  if (restoreFocus) trigger?.focus();
}

function openToolsMenu() {
  const menu = $('#tools-menu');
  const trigger = $('#tools-menu-button');
  if (!menu || !trigger) return;
  menu.hidden = false;
  trigger.setAttribute('aria-expanded', 'true');
  toolsMenuItems()[0]?.focus();

  toolsMenuOutsideHandler = (event) => {
    if (menu.contains(event.target) || trigger.contains(event.target)) return;
    closeToolsMenu();
  };
  toolsMenuKeyHandler = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeToolsMenu({ restoreFocus: true });
      return;
    }
    if (event.key === 'Tab') {
      closeToolsMenu();
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const items = toolsMenuItems();
    if (!items.length) return;
    const step = event.key === 'ArrowDown' ? 1 : -1;
    const current = items.indexOf(document.activeElement);
    const next = (current + step + items.length) % items.length;
    items[next].focus();
  };
  // Capture, so the menu closes before any handler bound to the trigger row.
  setTimeout(() => {
    document.addEventListener('mousedown', toolsMenuOutsideHandler, true);
    document.addEventListener('keydown', toolsMenuKeyHandler, true);
  }, 0);
}

function wireToolsMenu() {
  const menu = $('#tools-menu');
  const trigger = $('#tools-menu-button');
  if (!menu || !trigger) return;
  menu.querySelectorAll('.mini-button').forEach((button) => button.setAttribute('role', 'menuitem'));
  trigger.addEventListener('click', () => {
    if (menu.hidden) openToolsMenu();
    else closeToolsMenu({ restoreFocus: true });
  });
  // Capture phase: focus is back on the trigger before the tool's own handler
  // runs, so a modal it opens returns focus somewhere still visible.
  menu.addEventListener('click', (event) => {
    if (!event.target.closest('.mini-button')) return;
    closeToolsMenu({ restoreFocus: true });
  }, true);
}

// ----- Popup menu component -------------------------------------------------
// One shared <ul> element reused across the dashboard. Anchors to a trigger
// element, positions itself below it, closes on outside click / Escape, and
// supports keyboard arrow nav. Items: { id?, label, danger?, disabled?, onSelect }.
let popupMenuEl = null;
let popupMenuItems = [];
let popupMenuActiveIndex = 0;
let popupMenuOutsideHandler = null;
let popupMenuKeyHandler = null;
let popupMenuTrigger = null;

function closePopupMenu() {
  if (popupMenuEl) {
    popupMenuEl.remove();
    popupMenuEl = null;
  }
  // The trigger advertises the menu with aria-haspopup; its aria-expanded has
  // to come back down or assistive tech keeps reporting an open menu.
  popupMenuTrigger?.setAttribute('aria-expanded', 'false');
  popupMenuTrigger = null;
  popupMenuItems = [];
  document.removeEventListener('mousedown', popupMenuOutsideHandler, true);
  document.removeEventListener('keydown', popupMenuKeyHandler, true);
  popupMenuOutsideHandler = null;
  popupMenuKeyHandler = null;
}

function showPopupMenu(trigger, items) {
  closePopupMenu();
  if (!Array.isArray(items) || items.length === 0) return;
  popupMenuItems = items.filter((item) => !item.hidden);
  popupMenuTrigger = trigger;
  trigger?.setAttribute('aria-haspopup', 'menu');
  trigger?.setAttribute('aria-expanded', 'true');

  const menu = document.createElement('ul');
  menu.className = 'popup-menu';
  menu.setAttribute('role', 'menu');
  popupMenuItems.forEach((item, index) => {
    if (item.separator) {
      const sep = document.createElement('li');
      sep.className = 'popup-menu-separator';
      sep.setAttribute('role', 'separator');
      menu.appendChild(sep);
      return;
    }
    const li = document.createElement('li');
    li.setAttribute('role', 'menuitem');
    li.className = `popup-menu-item${item.danger ? ' danger' : ''}${item.disabled ? ' disabled' : ''}`;
    li.tabIndex = -1;
    li.textContent = item.label;
    li.title = item.title || '';
    li.dataset.index = String(index);
    if (!item.disabled) {
      li.addEventListener('click', (event) => {
        event.stopPropagation();
        closePopupMenu();
        try { item.onSelect?.(); } catch (err) { console.error(err); }
      });
    }
    menu.appendChild(li);
  });
  document.body.appendChild(menu);
  popupMenuEl = menu;

  // Position below the trigger, flipping above if it would overflow viewport.
  const rect = trigger.getBoundingClientRect();
  menu.style.visibility = 'hidden';
  requestAnimationFrame(() => {
    const menuRect = menu.getBoundingClientRect();
    const fitsBelow = rect.bottom + menuRect.height + 8 <= window.innerHeight;
    const top = fitsBelow
      ? rect.bottom + window.scrollY + 4
      : rect.top + window.scrollY - menuRect.height - 4;
    const left = Math.min(
      rect.left + window.scrollX,
      window.scrollX + window.innerWidth - menuRect.width - 8,
    );
    menu.style.top = `${Math.max(top, window.scrollY + 4)}px`;
    menu.style.left = `${Math.max(left, window.scrollX + 4)}px`;
    menu.style.visibility = 'visible';
    popupMenuActiveIndex = 0;
    const first = menu.querySelector('.popup-menu-item:not(.disabled)');
    first?.classList.add('active');
    first?.focus();
  });

  popupMenuOutsideHandler = (event) => {
    if (!popupMenuEl) return;
    if (popupMenuEl.contains(event.target) || trigger.contains(event.target)) return;
    closePopupMenu();
  };
  popupMenuKeyHandler = (event) => {
    if (!popupMenuEl) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      closePopupMenu();
      trigger.focus();
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      // Skip separators; only enabled non-separator items are focusable.
      const enabled = popupMenuItems
        .map((item, idx) => ({ item, idx }))
        .filter(({ item }) => !item.disabled && !item.separator);
      if (enabled.length === 0) return;
      const pos = enabled.findIndex(({ idx }) => idx === popupMenuActiveIndex);
      const next = enabled[(pos + step + enabled.length) % enabled.length];
      popupMenuActiveIndex = next.idx;
      menu.querySelectorAll('.popup-menu-item').forEach((el, idx) => {
        el.classList.toggle('active', idx === popupMenuActiveIndex);
      });
      menu.querySelector(`.popup-menu-item[data-index="${popupMenuActiveIndex}"]`)?.focus();
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      const current = popupMenuItems[popupMenuActiveIndex];
      if (current && !current.disabled) {
        closePopupMenu();
        try { current.onSelect?.(); } catch (err) { console.error(err); }
      }
    }
  };
  // Use capture so the outside-click fires before any handler bound to the
  // trigger element (e.g. our row-click listener).
  setTimeout(() => {
    document.addEventListener('mousedown', popupMenuOutsideHandler, true);
    document.addEventListener('keydown', popupMenuKeyHandler, true);
  }, 0);
}

// ----- Tracked-server polling ----------------------------------------------
// The dashboard used to learn that a server had died only when someone pressed
// Refresh. This loop re-reads /api/servers on its own: quickly while something
// is running or starting, slowly otherwise, paused while the tab is hidden. It
// repaints only when the tracked state actually changed, so idle ticks never
// disturb focus, scroll position, or in-progress parameter edits (the form is
// never re-rendered from here).
const SERVER_POLL_ACTIVE_MS = 5000;
const SERVER_POLL_IDLE_MS = 30000;
let serverPollTimer = null;

function serversBusy(servers) {
  return (servers || []).some((server) => (
    server.running || server.status === 'starting' || server.status === 'startup_timeout'
  ));
}

// Everything the server cards, badges and profile rows draw. Fields outside
// this list (metrics, log tails) are enrichment and must not force a repaint.
function serverStateSignature(servers) {
  return (servers || []).map((server) => [
    server.id,
    server.mode,
    server.running ? 'up' : 'down',
    server.status || '',
    server.pid ?? '',
    server.port ?? '',
    server.oom_likely ? 'oom' : '',
  ].join(':')).join('|');
}

// Replacing innerHTML drops focus to <body>. Remember which control was
// focused by its data-* identity and hand focus back to its counterpart in the
// new markup, so a background poll never moves the keyboard out from under the
// user mid-task.
function withFocusPreserved(render) {
  const active = document.activeElement;
  const data = active && active.dataset ? { ...active.dataset } : null;
  const identified = data && (data.serverId || data.profileMode || data.mode);
  const tag = active?.tagName;
  render();
  if (!identified) return;
  if (document.activeElement && document.activeElement !== document.body) return;
  const match = $$('[data-server-id], [data-profile-mode], [data-mode]').find((el) => (
    el.tagName === tag
    && el.dataset.serverId === data.serverId
    && el.dataset.profileMode === data.profileMode
    && el.dataset.mode === data.mode
    && el.dataset.action === data.action
  ));
  if (match && typeof match.focus === 'function') match.focus({ preventScroll: true });
}

// A server that was running and is not any more is news: say so once, naming
// the profile the way the rest of the UI names it.
function announceServerTransitions(previousById, servers) {
  servers.forEach((server) => {
    const before = previousById.get(server.id);
    if (!before || !before.running || server.running) return;
    const name = profileLabel(server.mode);
    const crashed = server.status === 'crashed' || !!server.last_stderr;
    toast(
      crashed ? `"${name}" crashed — open its logs for the reason` : releasedToast(server, name),
      crashed
        ? {
            label: 'Open logs',
            onClick: () => {
              state.selectedServerId = server.id;
              loadLogs(server.id, null, { silent: true });
              showPanel('logs');
            },
          }
        : undefined,
    );
  });
}

async function pollServers() {
  if (refreshInFlight) return;
  const generation = refreshGeneration;
  let servers;
  try {
    const data = await api('/api/servers');
    servers = data.servers || [];
  } catch {
    return; // Transient: the next tick retries.
  }
  // A full refresh may have started or landed while this request was in
  // flight; its data is newer, so drop ours rather than writing stale state
  // back over a stop or start the user just performed.
  if (refreshInFlight || refreshGeneration !== generation) return;
  const previous = state.servers || [];
  if (serverStateSignature(previous) === serverStateSignature(servers)) return;
  const previousById = new Map(previous.map((server) => [server.id, server]));
  servers.forEach((server) => {
    // /api/servers carries no metrics; keep the last enrichment so the metrics
    // line does not blink out between full refreshes.
    if (server.metrics === undefined) {
      const before = previousById.get(server.id);
      if (before?.metrics) server.metrics = before.metrics;
    }
  });
  state.servers = servers;
  withFocusPreserved(() => {
    renderServers();
    renderProfiles();
    renderLaunchLock();
  });
  announceServerTransitions(previousById, servers);
}

function scheduleServerPoll(delay) {
  window.clearTimeout(serverPollTimer);
  const wait = delay ?? (serversBusy(state.servers) ? SERVER_POLL_ACTIVE_MS : SERVER_POLL_IDLE_MS);
  serverPollTimer = window.setTimeout(runServerPollTick, wait);
}

async function runServerPollTick() {
  if (!document.hidden) await pollServers();
  scheduleServerPoll();
}

function startServerPolling() {
  scheduleServerPoll();
  document.addEventListener('visibilitychange', () => {
    // Catch up soon after the tab comes back, without a thundering herd.
    if (!document.hidden) scheduleServerPoll(400);
  });
}

// ----- Live Hardware polling (sidebar widget) -------------------------------
// Polls /api/system/live every few seconds, pauses when the tab is hidden or
// the sidebar is collapsed, and renders GPU util/temp/VRAM bars plus a RAM
// bar inside the sidebar just above the API footer.
const LIVE_HARDWARE_INTERVAL_MS = 3000;
let liveHardwareTimer = null;
const LIVE_HISTORY_MAX = 20; // ~60 seconds of history
let liveGpuUtilHistory = {}; // { idx: number[] }
let liveGpuVramHistory = {}; // { idx: number[] }
let liveRamHistory = []; // number[]

function liveBarClass(percent) {
  if (percent >= 90) return 'danger';
  if (percent >= 70) return 'warn';
  return '';
}

// Canvas cannot read CSS variables, so the tokens are resolved at draw time.
// One getComputedStyle per draw is cheap at this cadence and means a theme
// switch (or an OS-level one, while following the system) needs no extra
// bookkeeping: the next 3 s tick already paints in the new palette.
function themeColor(token, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  return value || fallback;
}

// The series colour reports the reading, it does not decorate it: accent while
// healthy, amber when the bar is warning, red only at the danger threshold —
// the same cutoffs liveBarClass() uses for the bars above each sparkline.
function seriesColor(values) {
  const latest = Number(values?.[values.length - 1] ?? 0);
  if (latest >= 90) return themeColor('--red', '#c4453e');
  if (latest >= 70) return themeColor('--amber', '#96650a');
  return themeColor('--accent', '#077076');
}

// Canvas has no alpha channel on a bare hex, and the fill wants one. Six-digit
// hex gets an alpha pair appended; anything else is passed through unchanged.
function withAlpha(color, hexAlpha) {
  return /^#[0-9a-f]{6}$/i.test(color) ? `${color}${hexAlpha}` : color;
}

function drawSparkline(canvas, values, color = themeColor('--accent', '#077076')) {
  if (!canvas || !values || values.length < 2) {
    if (canvas) {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
    return;
  }
  const ctx = canvas.getContext('2d');
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);

  const n = values.length;
  const max = Math.max(...values, 100);
  const min = Math.min(...values, 0);
  const range = (max - min) || 1;

  // subtle fill under the line
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = (i / (n - 1)) * w;
    const y = h - ((v - min) / range) * h;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.lineTo(w, h);
  ctx.lineTo(0, h);
  ctx.closePath();
  ctx.fillStyle = withAlpha(color, '22'); // very transparent
  ctx.fill();

  // line
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = (i / (n - 1)) * w;
    const y = h - ((v - min) / range) * h;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.8;
  ctx.lineJoin = 'round';
  ctx.stroke();

  // small end dot
  const lastX = w;
  const lastY = h - ((values[values.length-1] - min) / range) * h;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(lastX - 1, lastY, 2, 0, Math.PI * 2);
  ctx.fill();
}

function renderLiveGpu(gpu) {
  const usedPct = gpu.total_memory_bytes > 0
    ? (gpu.used_memory_bytes / gpu.total_memory_bytes) * 100
    : 0;
  const utilPct = Number.isFinite(gpu.utilization_gpu_percent) ? gpu.utilization_gpu_percent : null;
  const temp = Number.isFinite(gpu.temperature_c) ? `${Math.round(gpu.temperature_c)}°C` : '–';
  const utilText = utilPct === null ? '–' : `${Math.round(utilPct)}%`;
  // Shorten common GPU name prefixes so they fit the narrow sidebar column.
  const displayName = String(gpu.name || '')
    .replace(/^NVIDIA GeForce /, '')
    .replace(/^NVIDIA /, '')
    .replace(/^AMD Radeon /, '')
    .replace(/^Intel /, '');
  const idx = gpu.index ?? 0;
  return `
    <div class="live-gpu-card" data-gpu-index="${escapeHtml(idx)}">
      <div class="live-gpu-card-head">
        <span class="gpu-name" title="${escapeHtml(gpu.name)}">${escapeHtml(displayName)}</span>
        <span class="gpu-stats">${utilText} · ${temp}</span>
      </div>
      <div class="live-bar-label"><span>VRAM</span><span>${formatBytes(gpu.used_memory_bytes)} / ${formatBytes(gpu.total_memory_bytes)}</span></div>
      <div class="live-bar"><div class="live-bar-fill ${liveBarClass(usedPct)}" style="--fill:${(usedPct / 100).toFixed(4)}"></div></div>
      <canvas class="sparkline" width="120" height="18" data-type="vram" aria-hidden="true"></canvas>
      <p class="sr-only">VRAM ${usedPct.toFixed(0)} percent, ${formatBytes(gpu.used_memory_bytes)} of ${formatBytes(gpu.total_memory_bytes)}.</p>
      <div class="live-bar-label" style="margin-top:2px"><span>Util %</span></div>
      <canvas class="sparkline" width="120" height="18" data-type="util" aria-hidden="true"></canvas>
      <p class="sr-only">GPU utilization ${utilPct === null ? 'unknown' : `${Math.round(utilPct)} percent`}.</p>
    </div>`;
}

function renderLiveRam(ram) {
  if (!ram || ram.total_bytes == null) {
    return '<p class="live-empty">System RAM not detected.</p>';
  }
  const used = ram.total_bytes - (ram.free_bytes ?? ram.total_bytes);
  const pct = ram.total_bytes > 0 ? (used / ram.total_bytes) * 100 : 0;
  return `
    <div class="live-bar-label">
      <span class="label-title">System RAM</span>
      <span>${formatBytes(used)} / ${formatBytes(ram.total_bytes)}</span>
    </div>
    <div class="live-bar"><div class="live-bar-fill ${liveBarClass(pct)}" style="--fill:${(pct / 100).toFixed(4)}"></div></div>
    <canvas class="sparkline" width="120" height="16" data-type="ram" aria-hidden="true"></canvas>
    <p class="sr-only">System RAM ${pct.toFixed(0)} percent, ${formatBytes(used)} of ${formatBytes(ram.total_bytes)}.</p>`;
}

function renderLiveHardware(data) {
  const gpuGrid = $('#live-gpu-grid');
  const ramRow = $('#live-ram-row');
  const empty = $('#live-empty');
  const badge = $('#live-source-badge');
  if (!gpuGrid) return;

  const gpus = Array.isArray(data?.gpus) ? data.gpus : [];
  const hasGpus = gpus.length > 0;
  const hasRam = !!(data?.system_ram && data.system_ram.total_bytes != null);

  if (hasGpus) {
    gpuGrid.innerHTML = gpus.map(renderLiveGpu).join('');
    empty.hidden = true;
    // draw sparklines after DOM update
    gpuGrid.querySelectorAll('.live-gpu-card').forEach(card => {
      const idx = parseInt(card.dataset.gpuIndex || '0', 10);
      const utilH = liveGpuUtilHistory[idx] || [];
      const vramH = liveGpuVramHistory[idx] || [];
      const utilCan = card.querySelector('canvas[data-type="util"]');
      const vramCan = card.querySelector('canvas[data-type="vram"]');
      if (utilCan) drawSparkline(utilCan, utilH, seriesColor(utilH));
      if (vramCan) drawSparkline(vramCan, vramH, seriesColor(vramH));
    });
  } else {
    gpuGrid.innerHTML = '';
    empty.hidden = hasRam;  // hide the placeholder if we at least have RAM data
    if (!hasRam) {
      empty.textContent = data?.source === 'none'
        ? 'GPU data unavailable (no nvidia-smi detected).'
        : 'Waiting for first sample…';
    }
  }
  ramRow.innerHTML = hasRam ? renderLiveRam(data.system_ram) : '';
  const ramCan = ramRow.querySelector('canvas[data-type="ram"]');
  if (ramCan) drawSparkline(ramCan, liveRamHistory, seriesColor(liveRamHistory));

  if (badge) {
    const age = data?.cached_age_ms;
    const label = hasGpus
      ? `nvidia-smi · ${age != null ? `${age}ms` : 'live'}`
      : 'RAM only';
    badge.textContent = label;
    badge.hidden = false;
  }
}

async function pollLiveHardware() {
  const widget = $('#sidebar-live-hardware');
  // Pause only when the tab is hidden. A collapsed sidebar still samples: the
  // request is cheap and the sparklines would otherwise come back empty after
  // every expand. Painting is what gets skipped. ``enhanceSidebar`` toggles
  // ``.sidebar-collapsed`` on ``.app-shell``, so check there (the ``.sidebar``
  // element itself never gets that class).
  if (!widget || document.hidden) return;
  const collapsed = !!document.querySelector('.app-shell')?.classList.contains('sidebar-collapsed');
  try {
    const data = await api('/api/system/live');
    recordLiveHistory(data);
    if (!collapsed) renderLiveHardware(data);
  } catch {
    // Transient — next tick will retry.
  }
}

function recordLiveHistory(data) {
  const gpus = Array.isArray(data?.gpus) ? data.gpus : [];
  gpus.forEach((gpu, i) => {
    const idx = gpu.index ?? i;
    const util = Number.isFinite(gpu.utilization_gpu_percent) ? gpu.utilization_gpu_percent : 0;
    if (!liveGpuUtilHistory[idx]) liveGpuUtilHistory[idx] = [];
    liveGpuUtilHistory[idx].push(util);
    if (liveGpuUtilHistory[idx].length > LIVE_HISTORY_MAX) liveGpuUtilHistory[idx].shift();

    const vramPct = (gpu.total_memory_bytes > 0) ? (gpu.used_memory_bytes / gpu.total_memory_bytes * 100) : 0;
    if (!liveGpuVramHistory[idx]) liveGpuVramHistory[idx] = [];
    liveGpuVramHistory[idx].push(vramPct);
    if (liveGpuVramHistory[idx].length > LIVE_HISTORY_MAX) liveGpuVramHistory[idx].shift();
  });

  const ram = data?.system_ram;
  if (ram && ram.total_bytes) {
    const used = ram.total_bytes - (ram.free_bytes ?? ram.total_bytes);
    const pct = ram.total_bytes > 0 ? (used / ram.total_bytes) * 100 : 0;
    liveRamHistory.push(pct);
    if (liveRamHistory.length > LIVE_HISTORY_MAX) liveRamHistory.shift();
  }
}

function startLiveHardwarePolling() {
  if (liveHardwareTimer) return;
  // Always fetch the first sample immediately (even if sidebar collapsed at load).
  // Subsequent interval updates will respect the pause checks inside pollLiveHardware.
  (async () => {
    try {
      const data = await api('/api/system/live');
      recordLiveHistory(data);
      renderLiveHardware(data);
    } catch {
      // will retry on interval
    }
  })();
  liveHardwareTimer = setInterval(pollLiveHardware, LIVE_HARDWARE_INTERVAL_MS);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) pollLiveHardware();
  });
  // Note: a previous draft added a ``transitionend`` re-poll on the sidebar.
  // That listener amplified polling ~7x because ``.live-bar-fill`` itself
  // has a 420ms transform transition and every render restarts the bar from
  // ``scaleX(0)`` — each transition bubbled ``transitionend`` back to the
  // sidebar and fired another poll. Removed; the 3 s cadence is short enough
  // that the worst-case post-expand wait is acceptable.
}

restoreParamOverrides();
restoreChatHistory();
wireEvents();
loadSamplingPresets();
refresh();
startServerPolling();
startLiveHardwarePolling();


// ----- Log follow -----------------------------------------------------------
// Re-fetches the tail on an interval while the toggle is on. Mirrors the live
// hardware widget: one interval, and the poll body bails while the tab is
// hidden rather than tearing the timer down and rebuilding it.
const LOG_FOLLOW_INTERVAL_MS = 2500;
let logFollowTimer = null;

async function pollLogTail() {
  if (document.hidden) return;
  const serverId = state.selectedServerId;
  if (!serverId) return;
  const view = document.getElementById('session-logs');
  if (view && view.hidden) return; // Logs tab is not on screen
  try {
    const result = await api(`/api/servers/${encodeURIComponent(serverId)}/logs?lines=160`);
    showLogPreview(result.stderr || 'No log output yet.', result.stdout || '');
  } catch {
    // Transient failures are expected while a server starts or stops; the next
    // tick retries. Toasting here would spam once a server dies.
  }
}

function startLogFollow() {
  if (logFollowTimer) return;
  pollLogTail();
  logFollowTimer = setInterval(pollLogTail, LOG_FOLLOW_INTERVAL_MS);
}

function stopLogFollow() {
  if (!logFollowTimer) return;
  clearInterval(logFollowTimer);
  logFollowTimer = null;
}

function initLogFollow() {
  const toggle = document.getElementById('log-follow');
  if (!toggle) return;
  toggle.addEventListener('change', () => {
    if (toggle.checked) startLogFollow();
    else stopLogFollow();
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && toggle.checked) pollLogTail();
  });
}

// ----- Global model rescan --------------------------------------------------
// Registration otherwise runs only at app startup, so a model dropped into a
// scan root mid-session stays invisible until a restart. Distinct from
// #portability-rescan, which rebuilds the inventory and its warnings.
async function rescanModels(trigger) {
  await withBusy(trigger, async () => {
    try {
      const result = await api('/api/profiles/scan', { method: 'POST', body: JSON.stringify({}) });
      const count = result.registered_count || 0;
      toast(count
        ? `Registered ${count} new profile${count === 1 ? '' : 's'}`
        : 'Rescanned - no new models found');
      await refresh();
    } catch (error) {
      toast(`Rescan failed: ${error.message}`);
    }
  });
}

function initModelsRescan() {
  const button = document.getElementById('models-rescan');
  if (!button) return;
  button.addEventListener('click', (event) => rescanModels(event.currentTarget));
}

initLogFollow();
initModelsRescan();
