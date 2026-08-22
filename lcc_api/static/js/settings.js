// Settings modal and portable config export.

import { refresh } from './refresh.js';
import { $, linesToList, listToLines } from './util.js';
import { state } from './state.js';
import { enhanceTooltips, toast, withBusy } from './feedback.js';
import { api } from './api.js';

export function renderSettings() {
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

export function openSettings({ focus = 'model-dirs' } = {}) {
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

export function closeSettings() {
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

export function detectedRuntimeRoots() {
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

export function collectSettings() {
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

export async function saveSettings(event) {
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
export function buildPortableExportSnapshot(config, inventory) {
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

export async function exportPortableConfig(trigger) {
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

// Event wiring for this panel, moved out of app.js's wireEvents().
export function initSettings() {
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
  $('#portability-open-settings')?.addEventListener('click', () => openSettings());
  $('#portability-rescan')?.addEventListener('click', async (e) => {
    await withBusy(e.currentTarget, async () => {
      await refresh();
      toast('Rescanned inventory and portability issues');
    });
  });
}
