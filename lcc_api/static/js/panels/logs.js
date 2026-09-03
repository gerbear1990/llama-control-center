// Logs panel.

import { $ } from '../util.js';
import { state } from '../state.js';
import { toast, withBusy } from '../feedback.js';
import { emptyStateInner, logsEmptyCopy } from '../copy.js';
import { api } from '../api.js';

export function showLogPreview(text, stdoutText) {
  const empty = $('#log-empty');
  const preview = $('#log-preview');
  if (empty) empty.hidden = true;
  if (preview) {
    // Only stay pinned if the reader is already at the bottom. Yanking the
    // scroll while they read back through a stack trace is how a "follow"
    // mode becomes unusable.
    const pinned = preview.scrollHeight - preview.scrollTop - preview.clientHeight < 24;
    preview.hidden = false;
    preview.textContent = text;
    if (pinned) preview.scrollTop = preview.scrollHeight;
  }
  const stdoutPane = $('#log-stdout');
  const stdoutWrap = $('#log-stream-stdout');
  if (stdoutPane && stdoutWrap) {
    const has = !!(stdoutText && stdoutText.trim());
    stdoutWrap.hidden = !has;
    if (has) {
      const pinned = stdoutPane.scrollHeight - stdoutPane.scrollTop - stdoutPane.clientHeight < 24;
      stdoutPane.textContent = stdoutText;
      if (pinned) stdoutPane.scrollTop = stdoutPane.scrollHeight;
    }
  }
}

export function showLogEmpty() {
  const empty = $('#log-empty');
  const preview = $('#log-preview');
  if (empty) {
    empty.hidden = false;
    empty.className = 'empty-state';
    empty.innerHTML = emptyStateInner(logsEmptyCopy());
  }
  if (preview) preview.hidden = true;
}

export async function loadLogs(serverId, trigger, options = {}) {
  await withBusy(trigger, async () => {
    try {
      const result = await api(`/api/servers/${encodeURIComponent(serverId)}/logs?lines=160`);
      state.selectedServerId = serverId;
      showLogPreview(result.stderr || 'No log output yet.', result.stdout || '');
      if (!options.silent) toast('Logs loaded');
    } catch (error) {
      toast(`Logs failed: ${error.message}`);
    }
  });
}

// ----- Log follow -----------------------------------------------------------
// Re-fetches the tail on an interval while the toggle is on. Mirrors the live
// hardware widget: one interval, and the poll body bails while the tab is
// hidden rather than tearing the timer down and rebuilding it.
export const LOG_FOLLOW_INTERVAL_MS = 2500;

export let logFollowTimer = null;

export async function pollLogTail() {
  if (document.hidden) return;
  const serverId = state.selectedServerId;
  if (!serverId) return;
  const view = document.getElementById('session-logs');
  if (view && view.hidden) return; // Logs tab is not on screen
  try {
    const result = await api(`/api/servers/${encodeURIComponent(serverId)}/logs?lines=160`);
    showLogPreview(result.stderr || 'No log output yet.', result.stdout || '');
  } catch {
    // Transient failures are expected while a server starts or stops; the next
    // tick retries. Toasting here would spam once a server dies.
  }
}

export function startLogFollow() {
  if (logFollowTimer) return;
  pollLogTail();
  logFollowTimer = setInterval(pollLogTail, LOG_FOLLOW_INTERVAL_MS);
}

export function stopLogFollow() {
  if (!logFollowTimer) return;
  clearInterval(logFollowTimer);
  logFollowTimer = null;
}

export function initLogFollow() {
  const toggle = document.getElementById('log-follow');
  if (!toggle) return;
  toggle.addEventListener('change', () => {
    if (toggle.checked) startLogFollow();
    else stopLogFollow();
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && toggle.checked) pollLogTail();
  });
}

// Event wiring for this panel, moved out of app.js's wireEvents().
export function initLogsPanel() {
  $('#open-logs-button').addEventListener('click', () => {
    const serverId = state.selectedServerId || state.servers[0]?.id;
    if (serverId) loadLogs(serverId);
    else toast('No tracked server to open logs for');
  });
}
