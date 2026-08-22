// Fit panel.

import { getSelectedProfile, profileLabel, renderProfiles, setSelectedProfileMode } from './profiles.js';
import { applyFitResultParams, collectOverrides, markAppliedFields, primaryGpu, renderParameters, saveCurrentOverrides, selectedMode, setParamOverrides } from './parameters.js';
import { setModelNote } from './models.js';
import { showLogPreview } from './logs.js';
import { $, escapeHtml, formatMib, formatNumber, hasOwn } from '../util.js';
import { renderTuneSummary, shouldAutoApplyTune } from '../tune.js';
import { state } from '../state.js';
import { refresh } from '../refresh.js';
import { fitItem, fitStatusLabel } from '../format.js';
import { confirmAction, toast, withBusy } from '../feedback.js';
import { api } from '../api.js';

export function renderTpsEstimate(estimate) {
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

export function renderMeasuredTps(tokensPerSecond, elapsed) {
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

export function shouldShowMeasuredTps() {
  if (!state.measuredTps || !state.lastBenchmarkKey) return false;
  const currentKey = estimateKey(selectedMode() || '', collectOverrides());
  return currentKey === state.lastBenchmarkKey;
}

export function renderFitEstimate(fit) {
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

export function clearMeasuredTps() {
  state.measuredTps = null;
  state.measuredElapsed = null;
  state.lastBenchmarkKey = '';
}

export function renderEstimatePending(message = 'Estimating launch...') {
  $('#fit-estimate').textContent = '-';
  $('#fit-detail').textContent = message;
  $('#tps-estimate').textContent = '-';
  $('#tps-detail').textContent = message;
  clearMeasuredTps();
}

export function estimateKey(mode, overrides) {
  return JSON.stringify({
    mode,
    overrides,
    gpu: primaryGpu()?.name || '',
    vram: primaryGpu()?.vram_total_bytes || 0,
    ram: state.hardware?.memory?.total_bytes || 0,
    cpu: state.hardware?.cpu?.logical_cores || 0,
  });
}

export function scheduleTpsEstimate(delay = 350) {
  window.clearTimeout(scheduleTpsEstimate.timer);
  scheduleTpsEstimate.timer = window.setTimeout(updateTpsEstimate, delay);
}

export async function updateTpsEstimate() {
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

export function parsedFitAccepted(suggestions) {
  return Object.keys(suggestions || {}).some((key) => key !== 'fitted_args');
}

export function fitRecommendation(applied, suggestions) {
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

export function renderFitSummary(result, applied) {
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

export function fitSummaryText(applied, suggestions, speedEstimate) {
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

export async function runFitTest() {
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

export function applyTuneSuggestion(index) {
  const suggestion = (state.tuneSuggestions || [])[index];
  if (!suggestion) return;
  applyTunedParams(suggestion.params);
  renderTpsEstimate(suggestion.speed_estimate);
  scheduleTpsEstimate(80);
  toast(`Applied ${suggestion.label || 'suggestion'}`);
}

export function applyTunedParams(tuned) {
  const mode = selectedMode();
  if (!mode) return {};
  const applied = { ...collectOverrides(), ...(tuned || {}) };
  setParamOverrides(mode, applied);
  renderParameters();
  markAppliedFields(tuned || {});
  return applied;
}

export async function runAutoTune() {
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

export async function loadSamplingPresets() {
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

export function applySamplingPreset() {
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

export function renderBenchmarkSummary(result) {
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

export function renderBenchmarkHistory() {
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

export async function runBenchmark() {
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

// Event wiring for this panel, moved out of app.js's wireEvents().
export function initFitPanel() {
  $('#smart-fit-button').addEventListener('click', runAutoTune);
  $('#sampling-suggest-button').addEventListener('click', applySamplingPreset);
  $('#fit-button').addEventListener('click', runFitTest);
  $('#benchmark-button').addEventListener('click', runBenchmark);
}
