import { $ } from './util.js';
import { state } from './state.js';

export async function api(path, options = {}) {
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

export function setApiStatus(ok, text, details) {
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

export function renderVersion() {
  const el = $('#app-version');
  if (!el) return;
  el.textContent = state.meta?.version ? `v${state.meta.version}` : '';
}

export async function loadDashboardResource(label, path, apply) {
  try {
    const data = await api(path);
    apply(data);
    return null;
  } catch (error) {
    return `${label}: ${error.message}`;
  }
}
