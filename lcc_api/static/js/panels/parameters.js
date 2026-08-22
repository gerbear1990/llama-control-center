// Parameters panel.

import { refresh } from '../refresh.js';
import { promptProfileDetails, toast, withBusy } from '../feedback.js';
import { consoleSummaryLine, getSelectedProfile, renderProfiles, serverRunningForMode, setSelectedProfileMode } from './profiles.js';
import { scheduleTpsEstimate } from './fit.js';
import { renderChatLog } from './chat.js';
import { $, escapeHtml, hasOwn } from '../util.js';
import { state } from '../state.js';
import { launchControlState, launchLockCopy, launchLockHtml } from '../launch.js';
import { api } from '../api.js';

export const PARAM_DEFAULTS = {
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

export const FIT_APPLIED_FIELDS = [
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

// Live port-availability indicator next to the Port field. Probes
// /api/system/check-port on every edit (debounced 350ms) and renders a
// green dot when the port is free, a red dot when something else is
// bound there, and a grey dot while the probe is in flight.
export let portCheckTimer = null;

export let portCheckSeq = 0;

// The dot is a real control (role="button", Enter/Space re-probes), so the
// state it carries has to reach assistive tech too: title and aria-label are
// written together and never drift apart.
export function setPortStatus(stateClass, text) {
  const statusEl = $('#param-port-status');
  if (!statusEl) return;
  statusEl.className = `port-status ${stateClass}`;
  statusEl.title = `${text} — click to check again`;
  statusEl.setAttribute('aria-label', `${text}. Check port again.`);
}

export async function checkPortNow(port, host) {
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

export function schedulePortCheck() {
  window.clearTimeout(portCheckTimer);
  portCheckTimer = window.setTimeout(() => {
    const portInput = $('#param-port');
    const port = numericValue(portInput);
    if (!port) return;
    const host = $('#param-host')?.value.trim() || '127.0.0.1';
    checkPortNow(port, host);
  }, 350);
}

export function primaryGpu() {
  return state.hardware?.primary_gpu || state.hardware?.gpus?.[0] || null;
}

export function detectedThreadDefault() {
  const cpu = state.hardware?.cpu || {};
  return cpu.physical_cores || cpu.logical_cores || PARAM_DEFAULTS.threads;
}

export function detectedHeadroomDefault() {
  return state.hardware?.recommended_fit_target_mib || PARAM_DEFAULTS.fit_target_mib;
}

export function systemName() {
  return state.hardware?.platform?.system || '';
}

export function accelerationOptions() {
  const options = ['auto', ...(primaryGpu()?.acceleration_options || []), 'cpu'];
  if (systemName() === 'Darwin') options.push('metal');
  return Array.from(new Set(options.filter(Boolean).map((value) => String(value).toLowerCase())));
}

export function accelerationLabel(value) {
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

export function paramDefaults() {
  const threads = detectedThreadDefault();
  return {
    ...PARAM_DEFAULTS,
    threads,
    threads_batch: threads,
    fit_target_mib: detectedHeadroomDefault(),
  };
}

export function getProfileParams(profile) {
  if (!profile) return {};
  return { ...paramDefaults(), ...(profile.params || {}), ...(state.paramOverrides[profile.mode] || {}) };
}

// Parameter overrides are unsaved work: they used to live only in memory and
// vanish on reload. They now round-trip through localStorage (one entry, keyed
// by profile mode inside it) and are cleared when the profile is saved or reset.
export const PARAM_OVERRIDES_KEY = 'lcc-param-overrides';

export function persistParamOverrides() {
  try {
    localStorage.setItem(PARAM_OVERRIDES_KEY, JSON.stringify(state.paramOverrides));
  } catch { /* private mode or quota: overrides simply stay in memory */ }
}

export function restoreParamOverrides() {
  try {
    const raw = JSON.parse(localStorage.getItem(PARAM_OVERRIDES_KEY));
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) state.paramOverrides = raw;
  } catch { /* malformed entry: start clean */ }
}

export function setParamOverrides(mode, overrides) {
  if (!mode) return overrides;
  state.paramOverrides[mode] = overrides;
  persistParamOverrides();
  renderDirtyChip();
  return overrides;
}

export function clearParamOverrides(mode) {
  if (!mode) return;
  delete state.paramOverrides[mode];
  persistParamOverrides();
  renderDirtyChip();
}

// Drop drafts for profiles that no longer exist, so a deleted profile cannot
// leave its overrides behind forever.
export function pruneParamOverrides() {
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
export function sameParamValue(a, b) {
  if (a === b) return true;
  if (typeof a === 'boolean' || typeof b === 'boolean') return Boolean(a) === Boolean(b);
  return String(a ?? '') === String(b ?? '');
}

export function paramOverridesDirty(profile) {
  const overrides = profile && state.paramOverrides[profile.mode];
  if (!overrides) return false;
  const saved = { ...paramDefaults(), ...(profile.params || {}) };
  return Object.keys(overrides).some((key) => !sameParamValue(saved[key], overrides[key]));
}

export function renderDirtyChip() {
  const chip = $('#param-dirty-chip');
  if (!chip) return;
  chip.hidden = !paramOverridesDirty(getSelectedProfile());
}

export function setFieldValue(id, value) {
  const el = $(id);
  if (!el) return;
  if (el.type === 'checkbox') {
    el.checked = Boolean(value);
  } else {
    el.value = value ?? '';
  }
}

export function renderParamProfileOptions() {
  const select = $('#param-profile');
  select.innerHTML = state.profiles.map((profile) => (
    `<option value="${escapeHtml(profile.mode)}">${escapeHtml(profile.name || profile.mode)}</option>`
  )).join('');
  const selected = getSelectedProfile();
  if (selected) select.value = selected.mode;
}

export function renderRuntimeOptions(selectedValue) {
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

export function renderAccelerationOptions(selectedValue) {
  const select = $('#param-acceleration');
  const selected = String(selectedValue || 'auto').toLowerCase();
  const options = accelerationOptions();
  if (!options.includes(selected)) options.push(selected);
  select.innerHTML = options.map((value) => (
    `<option value="${escapeHtml(value)}">${escapeHtml(accelerationLabel(value))}</option>`
  )).join('');
}

export function renderParameters() {
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

export function numericValue(id) {
  const raw = $(id).value;
  if (raw === '') return undefined;
  return Number(raw);
}

export function collectOverrides() {
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

export function selectedMode() {
  return $('#param-profile').value || state.selectedProfileMode || state.profiles[0]?.mode;
}

export function saveCurrentOverrides() {
  const mode = selectedMode();
  if (!mode) return {};
  return setParamOverrides(mode, collectOverrides());
}

export function setLaunchWaiting(waiting) {
  const button = $('#start-selected-button');
  const label = $('#start-selected-label');
  if (label) label.textContent = waiting ? 'Waiting to listen' : 'Start server';
  if (button) {
    if (waiting) button.setAttribute('aria-label', 'Waiting for the server to listen');
    else button.removeAttribute('aria-label');
  }
  renderLaunchControls(waiting);
}

export function renderLaunchControls(waiting) {
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

export function renderLaunchLock(options = {}) {
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

export function markAppliedFields(params) {
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

export function applyFitResultParams(result) {
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

// Event wiring for this panel, moved out of app.js's wireEvents().
export function initParametersPanel() {
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
  $('#param-port-status')?.addEventListener('click', () => schedulePortCheck());
  $('#param-port-status')?.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    schedulePortCheck();
  });
  $('#param-ctx-preset').addEventListener('change', (event) => {
    const value = event.target.value;
    event.target.value = '';
    if (!value) return;
    const ctx = $('#param-ctx');
    ctx.value = value;
    ctx.dispatchEvent(new Event('input', { bubbles: true }));
    ctx.dispatchEvent(new Event('change', { bubbles: true }));
  });
}
