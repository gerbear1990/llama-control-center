const state = {
  inventory: null,
  config: null,
  hardware: null,
  profiles: [],
  servers: [],
  selectedProfileMode: null,
  selectedServerId: null,
  paramOverrides: {},
  lastEstimateKey: '',
  profileFilter: 'all',
  query: '',
  theme: localStorage.getItem('lcc-theme') || 'light',
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object || {}, key);
const PARAM_DEFAULTS = {
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

function toast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.add('show');
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => el.classList.remove('show'), 2800);
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

function applyTheme() {
  document.documentElement.dataset.theme = state.theme === 'dark' ? 'dark' : 'light';
  $('#theme-button').innerHTML = `<span class="theme-glyph" aria-hidden="true"></span>${state.theme === 'dark' ? 'Light' : 'Theme'}`;
}

function enhanceTooltips() {
  $$([
    '#param-form .field[title]',
    '#param-form .check-row label[title]',
    '#param-form .estimate-card[title]',
    '#settings-form .field[title]',
    '.hardware-chip[title]',
  ].join(',')).forEach((el) => {
    const text = el.getAttribute('title');
    if (!text || el.dataset.tooltipEnhanced === 'true') return;
    el.dataset.tooltipEnhanced = 'true';
    el.removeAttribute('title');
    const target = (el.classList.contains('field') || el.classList.contains('hardware-chip') || el.classList.contains('estimate-card'))
      ? el.querySelector('span')
      : el;
    if (!target) return;
    const help = document.createElement('span');
    help.className = 'help-dot';
    help.dataset.tooltip = text;
    help.tabIndex = 0;
    help.setAttribute('role', 'button');
    help.setAttribute('aria-label', text);
    help.textContent = 'i';
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
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}

function setApiStatus(ok, text) {
  const dot = $('#api-dot');
  dot.classList.toggle('ok', ok);
  dot.classList.toggle('error', !ok);
  $('#api-status').textContent = text;
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

function runtimeLine(label, value, extraClass = '') {
  return `
    <div class="runtime-line ${extraClass}">
      <span>${escapeHtml(label)}</span>
      <code title="${escapeHtml(value || '-')}">${escapeHtml(value || '-')}</code>
    </div>
  `;
}

function renderSummary() {
  const summary = state.inventory?.summary || {};
  $('#metric-runtimes').textContent = `${summary.available_environment_count ?? 0}/${summary.environment_count ?? 0}`;
  $('#metric-launchable').textContent = state.profiles.filter((profile) => profile.launchable).length;
  $('#metric-models').textContent = summary.model_count ?? 0;
  const needsSetup = state.profiles.filter((profile) => !profile.launchable).length + (summary.legacy_portability_issue_count ?? 0);
  $('#metric-setup').textContent = needsSetup;
  $('#summary-line').textContent = `${state.profiles.length} profiles, ${summary.model_count ?? 0} models, ${summary.legacy_portability_issue_count ?? 0} portability issues.`;
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

function renderHardware() {
  const cpu = state.hardware?.cpu || {};
  const gpu = primaryGpu();
  const cores = cpu.physical_cores ? `${cpu.physical_cores} cores` : (cpu.logical_cores ? `${cpu.logical_cores} threads` : '');
  $('#hardware-cpu').textContent = [cpu.name, cores].filter(Boolean).join(' · ') || '-';
  $('#hardware-gpu').textContent = gpu?.name || 'Not detected';
  $('#hardware-vram').textContent = formatBytes(gpu?.vram_total_bytes);
  $('#hardware-ram').textContent = formatBytes(state.hardware?.memory?.total_bytes);
}

function getSelectedProfile() {
  return state.profiles.find((profile) => profile.mode === state.selectedProfileMode) || state.profiles[0] || null;
}

function getProfileParams(profile) {
  if (!profile) return {};
  return { ...paramDefaults(), ...(profile.params || {}), ...(state.paramOverrides[profile.mode] || {}) };
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
  renderAccelerationOptions(params.acceleration_backend);
  setFieldValue('#param-host', params.host);
  setFieldValue('#param-port', params.port);
  setFieldValue('#param-acceleration', params.acceleration_backend || 'auto');
  setFieldValue('#param-device', params.device || 'auto');
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
  setFieldValue('#param-mmap', params.mmap);
  scheduleTpsEstimate(80);
}

function numericValue(id) {
  const raw = $(id).value;
  if (raw === '') return undefined;
  return Number(raw);
}

function collectOverrides() {
  return {
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
    mmap: $('#param-mmap').checked,
  };
}

function selectedMode() {
  return $('#param-profile').value || state.selectedProfileMode || state.profiles[0]?.mode;
}

function saveCurrentOverrides() {
  const mode = selectedMode();
  if (!mode) return {};
  const overrides = collectOverrides();
  state.paramOverrides[mode] = overrides;
  return overrides;
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
  state.paramOverrides[mode] = applied;
  renderParameters();
  markAppliedFields(applied);
  return applied;
}

function renderRuntimes() {
  const envs = state.inventory?.environments || [];
  $('#runtime-grid').innerHTML = envs.map((env) => {
    const url = runtimeUrl(env);
    const port = runtimePort(env);
    const warning = env.warnings?.[0] || env.details?.probe_error || '';
    return `
      <article class="runtime-card">
        <div class="runtime-card-top">
          <span class="badge ${env.available ? 'ok' : 'warn'}">${env.available ? 'ready' : 'not found'}</span>
          <span class="runtime-kind">${escapeHtml(env.kind || env.id || 'runtime')}</span>
        </div>
        <strong>${escapeHtml(env.name)}</strong>
        ${env.version ? `<small>${escapeHtml(env.version)}</small>` : ''}
        <div class="runtime-facts">
          ${runtimeLine('Location', runtimeLocation(env), env.binary_path ? '' : 'muted')}
          ${runtimeLine(env.api_url ? 'URL' : 'Probe URL', url || 'Not configured', url ? '' : 'muted')}
          ${runtimeLine('Port', port || 'Not configured', port ? '' : 'muted')}
        </div>
        ${warning ? `<p class="runtime-warning">${escapeHtml(warning)}</p>` : ''}
      </article>
    `;
  }).join('') || '<div class="loading">No runtimes detected.</div>';
}

function statusBadge(profile) {
  if (profile.launchable) return '<span class="badge ok">Launchable</span>';
  return '<span class="badge warn">Needs setup</span>';
}

function fitBadge(profile) {
  const fit = profile.fit_status;
  if (!fit) return '<span class="badge">Unknown</span>';
  const status = fit.status || 'unknown';
  const estimated = fit.estimated || {};
  const parts = [];
  if (estimated.accelerator_headroom_mib !== undefined && estimated.accelerator_headroom_mib !== null) {
    parts.push(`VRAM ${formatMib(estimated.accelerator_headroom_mib)} free`);
  }
  if (fit.uses_ram_offload && estimated.ram_headroom_mib !== undefined && estimated.ram_headroom_mib !== null) {
    parts.push(`RAM ${formatMib(estimated.ram_headroom_mib)} free`);
  }
  const title = parts.join(' | ') || fit.warnings?.[0] || 'Fit estimate unavailable';
  return `<span class="badge ${fitStatusClass(status)}" title="${escapeHtml(title)}">${escapeHtml(fit.label || fitStatusLabel(status))}</span>`;
}

function filteredProfiles() {
  return state.profiles
    .filter((profile) => {
      if (state.profileFilter === 'launchable') return profile.launchable;
      if (state.profileFilter === 'setup') return !profile.launchable;
      return true;
    })
    .filter(profileMatches);
}

function renderProfiles() {
  const rows = filteredProfiles().map((profile) => {
    const selected = profile.mode === state.selectedProfileMode;
    const modelName = profile.model?.name || 'Unresolved model';
    const warningText = profile.warnings?.[0] || profile.missing?.join(', ') || '';
    return `
      <tr class="${selected ? 'selected' : ''}" data-profile-mode="${escapeHtml(profile.mode)}">
        <td>
          <div class="cell-title">${escapeHtml(profile.name || profile.mode)}</div>
          <div class="cell-subtitle">${escapeHtml(profile.mode)}</div>
        </td>
        <td>
          <div class="cell-title">${escapeHtml(modelName)}</div>
          <div class="cell-subtitle">${escapeHtml(warningText || `${Math.round((profile.confidence || 0) * 100)}% match`)}</div>
        </td>
        <td>${statusBadge(profile)}</td>
        <td>${fitBadge(profile)}</td>
        <td>${escapeHtml(profile.params?.ctx_size || '-')}</td>
        <td>${escapeHtml(profile.params?.port || '-')}</td>
        <td>
          <div class="row-actions">
            <button class="mini-button" type="button" data-action="prepare" data-mode="${escapeHtml(profile.mode)}">Prepare</button>
            <button class="mini-button primary" type="button" data-action="start" data-mode="${escapeHtml(profile.mode)}" ${profile.launchable ? '' : 'disabled'}>Start</button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
  $('#profiles-table').innerHTML = rows || '<tr><td colspan="7"><div class="empty-state">No profiles match the current filter.</div></td></tr>';
}

function renderModels() {
  const models = (state.inventory?.models || []).filter(modelMatches);
  $('#model-list').innerHTML = models.map((model) => `
    <article class="model-row">
      <strong>${escapeHtml(model.name)}</strong>
      <div class="model-meta">
        <span class="badge">${escapeHtml(model.quant || 'unknown quant')}</span>
        <span class="badge">${escapeHtml(formatBytes(model.size_bytes))}</span>
        <span class="badge">${escapeHtml(model.source)}</span>
      </div>
      <div class="model-path">${escapeHtml(model.path)}</div>
    </article>
  `).join('') || '<div class="loading">No models match the current search.</div>';
}

function renderServers() {
  const servers = state.servers || [];
  if (!servers.length) {
    $('#server-box').innerHTML = '<div class="empty-state">No tracked servers. Start a launchable profile to track one here.</div>';
    $('#log-preview').textContent = 'No tracked server selected.';
    return;
  }
  $('#server-box').innerHTML = servers.map((server) => `
    <article class="server-item" data-server-id="${escapeHtml(server.id)}">
      <span class="badge ${server.running ? 'ok' : 'warn'}">${server.running ? 'running' : server.status || 'stopped'}</span>
      <strong>${escapeHtml(server.mode)}</strong>
      <p>PID ${escapeHtml(server.pid)} on ${escapeHtml(server.host)}:${escapeHtml(server.port)}</p>
      <div class="row-actions">
        <button class="mini-button" type="button" data-action="logs" data-server-id="${escapeHtml(server.id)}">Open logs</button>
        <button class="mini-button" type="button" data-action="stop" data-server-id="${escapeHtml(server.id)}" ${server.running ? '' : 'disabled'}>Stop</button>
      </div>
    </article>
  `).join('');
}

function renderIssues() {
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

function renderModelInfo(content) {
  $('#model-info-box').innerHTML = content;
}

function renderTpsEstimate(estimate) {
  const value = $('#tps-estimate');
  const detail = $('#tps-detail');
  if (!estimate) {
    value.textContent = '-';
    detail.textContent = 'Waiting for model and hardware details.';
    return;
  }
  value.textContent = `${estimate.estimate_tps} tok/s`;
  detail.textContent = `${estimate.low_tps}-${estimate.high_tps} tok/s range, ${estimate.confidence} confidence`;
}

function renderFitEstimate(fit) {
  const value = $('#fit-estimate');
  const detail = $('#fit-detail');
  const card = $('#fit-estimate-card');
  card.classList.remove('status-good', 'status-tight', 'status-near-limit');
  if (!fit) {
    value.textContent = '-';
    detail.textContent = 'Waiting for model and hardware details.';
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
}

function renderEstimatePending(message = 'Estimating launch...') {
  $('#fit-estimate').textContent = '-';
  $('#fit-detail').textContent = message;
  $('#tps-estimate').textContent = '-';
  $('#tps-detail').textContent = message;
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
  $('#settings-extra-args').value = listToLines(config.extra_llama_args);
}

function openSettings() {
  renderSettings();
  $('#settings-modal').hidden = false;
  enhanceTooltips();
  $('#settings-model-dirs').focus();
}

function closeSettings() {
  $('#settings-modal').hidden = true;
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
    extra_llama_args: linesToList($('#settings-extra-args').value),
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

function renderAll() {
  renderSummary();
  renderHardware();
  renderRuntimes();
  renderProfiles();
  renderModels();
  renderServers();
  renderIssues();
  renderParameters();
  renderSettings();
}

async function refresh() {
  $('#refresh-button').disabled = true;
  setApiStatus(false, 'Refreshing');
  try {
    const failures = (await Promise.all([
      loadDashboardResource('inventory', '/api/inventory', (data) => { state.inventory = data; }),
      loadDashboardResource('profiles', '/api/profiles', (data) => { state.profiles = data.profiles || []; }),
      loadDashboardResource('servers', '/api/servers', (data) => { state.servers = data.servers || []; }),
      loadDashboardResource('settings', '/api/config', (data) => { state.config = data; }),
      loadDashboardResource('hardware', '/api/system', (data) => { state.hardware = data; }),
    ])).filter(Boolean);

    if (!state.selectedProfileMode && state.profiles.length) {
      state.selectedProfileMode = state.profiles[0].mode;
    } else if (state.selectedProfileMode && !state.profiles.some((profile) => profile.mode === state.selectedProfileMode)) {
      state.selectedProfileMode = state.profiles[0]?.mode || null;
    }
    state.lastEstimateKey = '';
    renderAll();
    if (failures.length) {
      const summary = failures.slice(0, 2).join('; ');
      const suffix = failures.length > 2 ? ` and ${failures.length - 2} more` : '';
      setApiStatus(false, failures.length >= 5 ? 'API error' : 'API partial');
      toast(`Refresh partial: ${summary}${suffix}`);
    } else {
      setApiStatus(true, 'API ready');
    }
  } catch (error) {
    setApiStatus(false, 'API error');
    toast(`Refresh failed: ${error.message}`);
  } finally {
    $('#refresh-button').disabled = false;
  }
}

async function prepareProfile(mode) {
  state.selectedProfileMode = mode || selectedMode();
  const overrides = saveCurrentOverrides();
  try {
    const result = await api('/api/servers/prepare', {
      method: 'POST',
      body: JSON.stringify({ mode: state.selectedProfileMode, overrides }),
    });
    $('#log-preview').textContent = result.command?.command_line || 'Prepared command unavailable.';
    renderProfiles();
    renderParameters();
    toast(`Prepared ${mode}`);
  } catch (error) {
    toast(`Prepare failed: ${error.message}`);
  }
}

async function startProfile(mode) {
  state.selectedProfileMode = mode || selectedMode();
  const overrides = saveCurrentOverrides();
  if (!window.confirm(`Start profile "${state.selectedProfileMode}" with the resolved local model and current parameters?`)) return;
  try {
    await api('/api/servers/start', {
      method: 'POST',
      body: JSON.stringify({ mode: state.selectedProfileMode, overrides, wait_ready: true, ready_timeout_seconds: 45 }),
    });
    toast(`Started ${state.selectedProfileMode}`);
    await refresh();
  } catch (error) {
    toast(`Start failed: ${error.message}`);
  }
}

async function runFitTest() {
  const mode = selectedMode();
  if (!mode) return;
  state.selectedProfileMode = mode;
  const overrides = saveCurrentOverrides();
  const target = Number($('#param-fit-target').value || 1024);
  renderModelInfo('Running fit test. This may take a moment...');
  try {
    const result = await api('/api/profiles/fit', {
      method: 'POST',
      body: JSON.stringify({ mode, overrides, target_mib: target, timeout_seconds: 180 }),
    });
    const applied = applyFitResultParams(result);
    const suggestions = result.suggestions || {};
    renderModelInfo(renderFitSummary(result, applied));
    renderTpsEstimate(result.speed_estimate);
    scheduleTpsEstimate(80);
    $('#log-preview').textContent = parsedFitAccepted(suggestions)
      ? fitSummaryText(applied, suggestions, result.speed_estimate)
      : (result.command_line || result.stdout || 'Fit test completed.');
    toast('Fit test complete');
  } catch (error) {
    renderModelInfo(`<strong>Fit test failed</strong>\n${escapeHtml(error.message)}`);
    toast(`Fit test failed: ${error.message}`);
  }
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

async function runBenchmark() {
  const mode = selectedMode();
  if (!mode) return;
  state.selectedProfileMode = mode;
  const profile = getSelectedProfile();
  if (!profile?.launchable) {
    toast('Choose a launchable profile before benchmarking');
    return;
  }
  if (!window.confirm(`Benchmark "${mode}" with the current parameters? This may restart the tracked server for this profile.`)) return;
  const overrides = saveCurrentOverrides();
  const requested = Number($('#param-predict').value || 128);
  const completionTokens = requested > 0 ? Math.min(requested, 512) : 128;
  renderModelInfo('Running benchmark with the current parameters...');
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
    renderModelInfo(renderBenchmarkSummary(result));
    $('#log-preview').textContent = [
      `Benchmark: ${result.benchmark.tokens_per_second} tok/s`,
      `Elapsed: ${result.benchmark.elapsed_seconds}s`,
      `Endpoint: ${result.benchmark.endpoint}`,
    ].join('\n');
    toast(`Benchmark: ${result.benchmark.tokens_per_second} tok/s`);
    await refresh();
  } catch (error) {
    renderModelInfo(`<strong>Benchmark failed</strong>\n${escapeHtml(error.message)}`);
    toast(`Benchmark failed: ${error.message}`);
  }
}

async function fetchHFInfo() {
  const profile = getSelectedProfile();
  if (!profile) return;
  renderModelInfo('Fetching Hugging Face metadata...');
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
    renderModelInfo(lines);
    toast('HF info loaded');
  } catch (error) {
    renderModelInfo(`<strong>HF lookup failed</strong>\n${escapeHtml(error.message)}`);
    toast(`HF lookup failed: ${error.message}`);
  }
}

async function stopTracked(serverId) {
  try {
    await api('/api/servers/stop', {
      method: 'POST',
      body: JSON.stringify({ server_id: serverId }),
    });
    toast('Stop requested');
    await refresh();
  } catch (error) {
    toast(`Stop failed: ${error.message}`);
  }
}

async function loadLogs(serverId) {
  try {
    const result = await api(`/api/servers/${encodeURIComponent(serverId)}/logs?lines=160`);
    state.selectedServerId = serverId;
    $('#log-preview').textContent = [result.stderr, result.stdout].filter(Boolean).join('\n\n') || 'No log output yet.';
    toast('Logs loaded');
  } catch (error) {
    toast(`Logs failed: ${error.message}`);
  }
}

function wireEvents() {
  applyTheme();
  enhanceTooltips();
  $('#refresh-button').addEventListener('click', refresh);
  $('#settings-button').addEventListener('click', openSettings);
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
  $('#theme-button').addEventListener('click', () => {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('lcc-theme', state.theme);
    applyTheme();
  });
  $('#search-input').addEventListener('input', (event) => {
    state.query = event.target.value;
    renderProfiles();
    renderModels();
  });
  $$('.segment').forEach((button) => {
    button.addEventListener('click', () => {
      $$('.segment').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      state.profileFilter = button.dataset.profileFilter;
      renderProfiles();
    });
  });
  document.body.addEventListener('click', (event) => {
    const target = event.target.closest('button');
    if (!target) return;
    const { action, mode, serverId } = target.dataset;
    if (mode && state.profiles.some((profile) => profile.mode === mode)) {
      state.selectedProfileMode = mode;
      renderParameters();
    }
    if (action === 'prepare') prepareProfile(mode);
    if (action === 'start') startProfile(mode);
    if (action === 'logs') loadLogs(serverId);
    if (action === 'stop') stopTracked(serverId);
  });
  $('#open-logs-button').addEventListener('click', () => {
    const serverId = state.selectedServerId || state.servers[0]?.id;
    if (serverId) loadLogs(serverId);
    else toast('No tracked server to open logs for');
  });
  $('#param-profile').addEventListener('change', (event) => {
    state.selectedProfileMode = event.target.value;
    renderParameters();
    renderProfiles();
  });
  $('#reset-params-button').addEventListener('click', () => {
    const mode = selectedMode();
    delete state.paramOverrides[mode];
    renderParameters();
    toast('Parameters reset');
  });
  $('#prepare-selected-button').addEventListener('click', () => prepareProfile(selectedMode()));
  $('#fit-button').addEventListener('click', runFitTest);
  $('#benchmark-button').addEventListener('click', runBenchmark);
  $('#hf-info-button').addEventListener('click', fetchHFInfo);
  $('#param-form').addEventListener('change', () => {
    saveCurrentOverrides();
    scheduleTpsEstimate();
  });
  $('#param-form').addEventListener('input', () => {
    saveCurrentOverrides();
    scheduleTpsEstimate();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !$('#settings-modal').hidden) closeSettings();
  });
  window.addEventListener('resize', hideFloatingTooltip);
  window.addEventListener('scroll', hideFloatingTooltip, true);
  $$('.nav-item').forEach((item) => {
    item.addEventListener('click', () => {
      $$('.nav-item').forEach((nav) => nav.classList.remove('active'));
      item.classList.add('active');
    });
  });
}

wireEvents();
refresh();
