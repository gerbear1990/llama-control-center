// Runtimes panel.

import { $, escapeHtml } from '../util.js';
import { state } from '../state.js';
import { toast, withBusy } from '../feedback.js';
import { emptyStateHtml, runtimesEmptyCopy } from '../copy.js';
import { api } from '../api.js';

export function runtimeUrl(env) {
  return env.api_url || env.details?.probe_url || '';
}

export function runtimePort(env) {
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

export function runtimeLocation(env) {
  return env.binary_path || env.details?.python_module || 'Not found on disk';
}

export function runtimeUpdateFor(runtimeId) {
  const updates = state.runtimeUpdates?.updates || [];
  return updates.find((item) => item.runtime_id === runtimeId) || null;
}

export function renderRuntimes() {
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

export async function refreshRuntimeUpdates(trigger) {
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

export async function recheckRuntime(runtimeId, trigger) {
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

// Event wiring for this panel, moved out of app.js's wireEvents().
export function initRuntimesPanel() {
  $('#check-updates-button').addEventListener('click', (event) => refreshRuntimeUpdates(event.currentTarget));
  const hideNotInstalled = $('#hide-not-installed-runtimes');
  if (hideNotInstalled) {
    hideNotInstalled.checked = !!state.hideNotInstalledRuntimes;
    hideNotInstalled.addEventListener('change', (event) => {
      state.hideNotInstalledRuntimes = event.target.checked;
      localStorage.setItem('lcc-hide-not-installed-runtimes', state.hideNotInstalledRuntimes ? '1' : '0');
      renderRuntimes();
    });
  }
}
