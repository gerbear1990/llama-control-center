// The dashboard refresh cycle: pull every resource, then re-render.
import { $ } from './util.js';
import { state } from './state.js';
import { renderSettings } from './settings.js';
import { renderServers, scheduleServerPoll } from './panels/servers.js';
import { renderRuntimes } from './panels/runtimes.js';
import { renderProfiles, setSelectedProfileMode } from './panels/profiles.js';
import { pruneParamOverrides, renderParameters, renderRuntimeOptions } from './panels/parameters.js';
import { renderModels, updateHfCliUi } from './panels/models.js';
import { renderIssues, renderPortability, renderSummary } from './panels/inventory.js';
import { renderBenchmarkHistory } from './panels/fit.js';
import { toast } from './feedback.js';
import { api, loadDashboardResource, renderVersion, setApiStatus } from './api.js';

// Panels import refresh() from here and this imports their renderers.
// The cycle is safe: both sides are function declarations, called at
// event time rather than while the modules are evaluating.

export const DASHBOARD_RESOURCES = [
  { label: 'profiles', path: '/api/profiles', apply: (d) => { state.profiles = d.profiles || []; }, render: () => { pruneParamOverrides(); reconcileSelectedMode(); renderProfiles(); renderParameters(); renderSummary(); } },
  { label: 'servers', path: '/api/servers', apply: (d) => { state.servers = d.servers || []; }, render: renderServers },
  { label: 'inventory', path: '/api/inventory', apply: (d) => { state.inventory = d; }, render: () => { renderSummary(); renderModels(); renderIssues(); renderRuntimes(); renderRuntimeOptions($('#param-runtime')?.value); renderPortability(); } },
  { label: 'settings', path: '/api/config', apply: (d) => { state.config = d; }, render: () => { renderSettings(); renderParameters(); renderPortability(); } },
  { label: 'hardware', path: '/api/system', apply: (d) => { state.hardware = d; }, render: renderParameters },
  { label: 'meta', path: '/api/meta', apply: (d) => { state.meta = d; }, render: renderVersion },
  { label: 'runtime-updates', path: '/api/runtime-updates', apply: (d) => { state.runtimeUpdates = d; }, render: renderRuntimes },
  { label: 'hf-cli', path: '/api/hf-cli', apply: (d) => { updateHfCliUi(d); }, render: () => {} },
  { label: 'benchmarks', path: '/api/benchmarks', apply: (d) => { state.benchmarks = d.benchmarks || []; }, render: renderBenchmarkHistory },
];

// The background server poll uses these two to tell whether its in-flight
// response is still the freshest view of the world.
export let refreshInFlight = false;

export let refreshGeneration = 0;

// Each resource fetches independently and repaints only its own sections as it
// resolves, so the dashboard paints progressively instead of blocking on the
// slowest endpoint (runtime-updates hits GitHub on a cold cache). Cross-cutting
// renders (e.g. renderSummary needs inventory+profiles) are listed on every
// input they read — idempotent, so running them more than once is harmless.
export function reconcileSelectedMode() {
  if (!state.selectedProfileMode && state.profiles.length) {
    setSelectedProfileMode(state.profiles[0].mode);
  } else if (state.selectedProfileMode && !state.profiles.some((profile) => profile.mode === state.selectedProfileMode)) {
    setSelectedProfileMode(state.profiles[0]?.mode || null);
  }
}

export async function refresh() {
  const refreshButton = $('#refresh-button');
  if (refreshButton) {
    refreshButton.disabled = true;
    refreshButton.setAttribute('aria-busy', 'true');
  }
  setApiStatus(false, 'Refreshing');
  state.lastEstimateKey = '';
  refreshInFlight = true;
  try {
    const failures = (await Promise.all(DASHBOARD_RESOURCES.map(async (resource) => {
      const error = await loadDashboardResource(resource.label, resource.path, resource.apply);
      if (!error) resource.render();
      return error;
    }))).filter(Boolean);
    if (failures.length) {
      const summary = failures.slice(0, 2).join('; ');
      const suffix = failures.length > 2 ? ` and ${failures.length - 2} more` : '';
      const detailText = failures.join('\n');
      setApiStatus(false, failures.length >= DASHBOARD_RESOURCES.length ? 'API error' : 'API partial', detailText);
      toast(`Refresh partial: ${summary}${suffix}`);
    } else {
      setApiStatus(true, 'API ready');
    }

    // M2 observability (M1.3/M2.1): extend polling to fetch /metrics for running/crashed
    // servers on refresh. Attach to the server objects in state so renderers can use them.
    // Logs remain on-demand via loadLogs (already wired in UI).
    try {
      const servers = state.servers || [];
      const toPoll = servers.filter((s) => s.running || s.status === 'crashed' || s.status === 'startup_timeout');
      if (toPoll.length > 0) {
        await Promise.all(toPoll.map(async (srv) => {
          try {
            const m = await api(`/api/servers/${encodeURIComponent(srv.id)}/metrics`);
            srv.metrics = m;
          } catch (_) {
            // non-fatal; render will show what it has
          }
        }));
        renderServers();
      }
    } catch (_) {
      // enrichment must never break refresh
    }
  } catch (error) {
    setApiStatus(false, 'API error', `API error: ${error.message}`);
    toast(`Refresh failed: ${error.message}`);
  } finally {
    refreshInFlight = false;
    refreshGeneration += 1;
    if (refreshButton) {
      refreshButton.disabled = false;
      refreshButton.removeAttribute('aria-busy');
    }
    scheduleServerPoll();
  }
}
