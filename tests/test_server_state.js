// Optimistic server-list updates must be pure and instant: Stop/Purge cannot
// wait on a full dashboard refresh before the cards move.
(async () => {
  const { markServersStopped, purgeServersState } = await import('../lcc_api/static/js/server-state.js');

  const running = { id: 'a', mode: 'qwen', running: true, status: 'running', pid: 1 };
  const stopped = { id: 'b', mode: 'old', running: false, status: 'stopped', pid: 2 };
  const crashed = { id: 'c', mode: 'boom', running: false, status: 'crashed', pid: 3 };

  const afterStop = markServersStopped([running, stopped], (s) => s.id === 'a');
  const afterModeStop = markServersStopped([running, stopped], (s) => s.mode === 'qwen' && s.running);
  const purged = purgeServersState([running, stopped, crashed], { onlyNonRunning: true });
  const cleared = purgeServersState([running, stopped], { all: true });

  const ok = (
    afterStop[0].running === false
    && afterStop[0].status === 'stopped'
    && afterStop[0].pid === 1
    && afterStop[1].running === false
    && afterModeStop[0].running === false
    && purged.length === 1
    && purged[0].id === 'a'
    && cleared.length === 0
  );

  console.log(JSON.stringify({
    ok,
    stoppedStatus: afterStop[0].status,
    purgedIds: purged.map((s) => s.id),
    cleared: cleared.length,
  }));
  process.exit(ok ? 0 : 1);
})();
