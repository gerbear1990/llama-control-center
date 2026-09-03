// Pure tracked-server list updates. Stop/Purge paint from these so the
// cards move before the API round-trip.

export function markServersStopped(servers, match) {
  return (servers || []).map((server) => (
    match(server)
      ? { ...server, running: false, status: 'stopped' }
      : server
  ));
}

export function purgeServersState(servers, { all = false, onlyNonRunning = true } = {}) {
  if (all) return [];
  if (onlyNonRunning) return (servers || []).filter((server) => server.running);
  return servers || [];
}
