import { escapeHtml } from './util.js';

// The launch lock: where a server is listening, and what the Start/Stop
// controls may say about it. Pure -- the panel owns the DOM.

export function serverEndpoint(server) {
  if (!server) return '';
  const host = String(server.host || '127.0.0.1').trim() || '127.0.0.1';
  const port = server.port;
  return port ? `${host}:${port}` : host;
}

export function serverUrl(server) {
  const endpoint = serverEndpoint(server);
  return endpoint ? `http://${endpoint}` : '';
}

export function launchLockCopy(server) {
  if (!server || !server.running) return null;
  const endpoint = serverEndpoint(server);
  if (!endpoint) return null;
  return {
    status: 'Listening',
    endpoint,
    detail: server.pid ? `PID ${server.pid}` : '',
  };
}

export function launchLockHtml(copy) {
  if (!copy) return '';
  const detail = copy.detail ? `<p class="launch-lock-detail">${escapeHtml(copy.detail)}</p>` : '';
  return `
    <div class="launch-lock-main">
      <span class="badge ok">${escapeHtml(copy.status)}</span>
      <strong class="launch-lock-endpoint">${escapeHtml(copy.endpoint)}</strong>
    </div>
    ${detail}
    <div class="launch-lock-actions">
      <button type="button" class="mini-button" data-launch-action="copy">Copy URL</button>
      <button type="button" class="mini-button" data-launch-action="chat">Open Chat</button>
    </div>`;
}

export function listeningToast(server, name) {
  const endpoint = serverEndpoint(server);
  return endpoint ? `Listening on ${endpoint}` : `Listening — ${name}`;
}

export function releasedToast(server, name) {
  const endpoint = serverEndpoint(server);
  return endpoint ? `Released ${endpoint}` : `"${name}" stopped`;
}

export function launchControlState(profile, server, waiting) {
  const live = server && server.running ? server : null;
  const endpoint = serverEndpoint(live);
  return {
    startDisabled: !profile || !profile.launchable || !!live || !!waiting,
    stopDisabled: !live,
    startTitle: live
      ? `Already listening on ${endpoint}`
      : (!profile
        ? 'Select a profile first'
        : (!profile.launchable ? 'This profile is not launchable' : 'Start server')),
    stopTitle: live ? `Stop ${endpoint}` : 'No running server for this profile',
  };
}
