import { escapeHtml, formatBytes, formatNumber } from './util.js';

// Compact relative-time formatter for the profile Updated column. Unix
export function fitStatusClass(status) {
  if (status === 'good') return 'ok';
  if (status === 'tight') return 'warn';
  if (status === 'near_limit') return 'error';
  return '';
}

export function fitStatusLabel(status) {
  return {
    good: 'Good',
    tight: 'Tight',
    near_limit: 'Near Limit',
    unknown: 'Unknown',
  }[status] || 'Unknown';
}

export function fitItem(label, value, unit = '') {
  if (value === undefined || value === null || value === '') return '';
  return `<li><span>${escapeHtml(label)}</span><strong>${escapeHtml(formatNumber(value))}${unit}</strong></li>`;
}

export function formatServerMetricsLine(m) {
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
export function buildServerMetricsRows(m) {
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
