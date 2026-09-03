// Hardware panel.

import { $, escapeHtml, formatBytes } from '../util.js';
import { api } from '../api.js';

// ----- Live Hardware polling (sidebar widget) -------------------------------
// Polls /api/system/live every few seconds, pauses when the tab is hidden or
// the sidebar is collapsed, and renders GPU util/temp/VRAM bars plus a RAM
// bar inside the sidebar just above the API footer.
export const LIVE_HARDWARE_INTERVAL_MS = 3000;

export let liveHardwareTimer = null;

export const LIVE_HISTORY_MAX = 20; // ~60 seconds of history

export let liveGpuUtilHistory = {}; // { idx: number[] }

export let liveGpuVramHistory = {}; // { idx: number[] }

export let liveRamHistory = []; // number[]

export function liveBarClass(percent) {
  if (percent >= 90) return 'danger';
  if (percent >= 70) return 'warn';
  return '';
}

// Canvas cannot read CSS variables, so the tokens are resolved at draw time.
// One getComputedStyle per draw is cheap at this cadence and means a theme
// switch (or an OS-level one, while following the system) needs no extra
// bookkeeping: the next 3 s tick already paints in the new palette.
export function themeColor(token, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  return value || fallback;
}

// The series colour reports the reading, it does not decorate it: accent while
// healthy, amber when the bar is warning, red only at the danger threshold —
// the same cutoffs liveBarClass() uses for the bars above each sparkline.
export function seriesColor(values) {
  const latest = Number(values?.[values.length - 1] ?? 0);
  if (latest >= 90) return themeColor('--red', '#c4453e');
  if (latest >= 70) return themeColor('--amber', '#96650a');
  return themeColor('--accent', '#077076');
}

// Canvas has no alpha channel on a bare hex, and the fill wants one. Six-digit
// hex gets an alpha pair appended; anything else is passed through unchanged.
export function withAlpha(color, hexAlpha) {
  return /^#[0-9a-f]{6}$/i.test(color) ? `${color}${hexAlpha}` : color;
}

export function drawSparkline(canvas, values, color = themeColor('--accent', '#077076')) {
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

export function renderLiveGpu(gpu) {
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

export function renderLiveRam(ram) {
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

export function renderLiveHardware(data) {
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

export async function pollLiveHardware() {
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

export function recordLiveHistory(data) {
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

export function startLiveHardwarePolling() {
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
