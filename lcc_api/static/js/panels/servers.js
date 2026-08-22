// Servers panel.

import { profileLabel, renderProfiles, setSelectedProfileMode } from './profiles.js';
import { collectOverrides, renderLaunchLock, renderParameters, selectedMode, setLaunchWaiting } from './parameters.js';
import { loadLogs, showLogEmpty, showLogPreview } from './logs.js';
import { liveBarClass } from './hardware.js';
import { $, $$, escapeHtml } from '../util.js';
import { state } from '../state.js';
import { revealPanel, showPanel } from '../router.js';
import { refresh, refreshGeneration, refreshInFlight } from '../refresh.js';
import { listeningToast, releasedToast, serverEndpoint } from '../launch.js';
import { buildServerMetricsRows, formatServerMetricsLine } from '../format.js';
import { confirmAction, setActionsBusy, toast, withBusy } from '../feedback.js';
import { emptyStateHtml, serversEmptyCopy } from '../copy.js';
import { api } from '../api.js';

// Selecting a card here is what the Logs panel reads.
export function renderServers() {
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
export function renderServerMetricsPanel() {
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

export function buildServerItemHtml(server) {
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

// ----- Tracked-server polling ----------------------------------------------
// The dashboard used to learn that a server had died only when someone pressed
// Refresh. This loop re-reads /api/servers on its own: quickly while something
// is running or starting, slowly otherwise, paused while the tab is hidden. It
// repaints only when the tracked state actually changed, so idle ticks never
// disturb focus, scroll position, or in-progress parameter edits (the form is
// never re-rendered from here).
export const SERVER_POLL_ACTIVE_MS = 5000;

export const SERVER_POLL_IDLE_MS = 30000;

export let serverPollTimer = null;

export function serversBusy(servers) {
  return (servers || []).some((server) => (
    server.running || server.status === 'starting' || server.status === 'startup_timeout'
  ));
}

// Everything the server cards, badges and profile rows draw. Fields outside
// this list (metrics, log tails) are enrichment and must not force a repaint.
export function serverStateSignature(servers) {
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
export function withFocusPreserved(render) {
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
export function announceServerTransitions(previousById, servers) {
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

export async function pollServers() {
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

export function scheduleServerPoll(delay) {
  window.clearTimeout(serverPollTimer);
  const wait = delay ?? (serversBusy(state.servers) ? SERVER_POLL_ACTIVE_MS : SERVER_POLL_IDLE_MS);
  serverPollTimer = window.setTimeout(runServerPollTick, wait);
}

export async function runServerPollTick() {
  if (!document.hidden) await pollServers();
  scheduleServerPoll();
}

export function startServerPolling() {
  scheduleServerPoll();
  document.addEventListener('visibilitychange', () => {
    // Catch up soon after the tab comes back, without a thundering herd.
    if (!document.hidden) scheduleServerPoll(400);
  });
}

export async function prepareProfile(mode, trigger) {
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

export async function startProfile(mode, trigger) {
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

export async function stopTracked(serverId, trigger) {
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

export async function restartTracked(serverId, trigger) {
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

export async function stopProfileByMode(mode, trigger) {
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

export async function purgeServers(onlyNonRunning = true, trigger = null, clearAll = false) {
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

// Event wiring for this panel, moved out of app.js's wireEvents().
export function initServersPanel() {
  $('#server-box')?.addEventListener('keydown', (event) => {
    const card = event.target.closest('.server-item');
    if (!card || event.target.closest('button')) return;
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    card.click();
  });
  $('#servers-purge-stopped')?.addEventListener('click', (e) => purgeServers(true, e.currentTarget));
  $('#servers-clear-history')?.addEventListener('click', (e) => purgeServers(false, e.currentTarget, true));
  $('#prepare-selected-button').addEventListener('click', (event) => prepareProfile(selectedMode(), event.currentTarget));
  $('#start-selected-button')?.addEventListener('click', (event) => startProfile(selectedMode(), event.currentTarget));
  $('#stop-selected-button')?.addEventListener('click', (event) => stopProfileByMode(selectedMode(), event.currentTarget));
}
