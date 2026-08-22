import { escapeHtml, formatNumber } from './util.js';
import { fitItem, fitStatusClass, fitStatusLabel } from './format.js';

export function tuneFieldLabel(field) {
  return {
    gpu_layers: 'GPU layers',
    ctx_size: 'Context',
    cache_type_k: 'KV cache K',
    cache_type_v: 'KV cache V',
  }[field] || field;
}

export function tuneValueLabel(field, value) {
  if (field === 'gpu_layers') return Number(value) >= 999 || value === 'all' ? 'all' : formatNumber(value);
  return value ?? '-';
}

export function shouldAutoApplyTune(result) {
  return !!(result && result.success && !result.cpu_fallback);
}

export function renderTuneNotes(notes) {
  if (!Array.isArray(notes) || !notes.length) return '';
  return `<ul class="tune-notes">${notes.map((note) => `<li>${escapeHtml(note)}</li>`).join('')}</ul>`;
}

export function renderTuneSuggestions(suggestions) {
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

export function renderTuneSummary(result, options = {}) {
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
