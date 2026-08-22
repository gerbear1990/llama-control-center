// Inventory panel.

import { getSelectedProfile, renderProfiles } from './profiles.js';
import { $, escapeHtml } from '../util.js';
import { state } from '../state.js';
import { DESTINATIONS, showPanel } from '../router.js';
import { refresh } from '../refresh.js';
import { toast, withBusy } from '../feedback.js';
import { emptyStateInner, stageFirstRunCopy } from '../copy.js';
import { api } from '../api.js';

export function renderSummary() {
  const summary = state.inventory?.summary || {};
  $('#metric-runtimes').textContent = `${summary.available_environment_count ?? 0}/${summary.environment_count ?? 0}`;
  $('#metric-launchable').textContent = state.profiles.filter((profile) => profile.launchable).length;
  $('#metric-models').textContent = summary.model_count ?? 0;
  const needsSetup = state.profiles.filter((profile) => !profile.launchable).length + (summary.legacy_portability_issue_count ?? 0);
  $('#metric-setup').textContent = needsSetup;
  const setupMetric = $('#metric-setup-wrapper');
  if (setupMetric) {
    setupMetric.setAttribute('aria-label', `${needsSetup} item${needsSetup === 1 ? '' : 's'} need setup. Show them in the profiles table.`);
  }
  const dest = $('.main')?.dataset.destination;
  if (dest === 'inventory') {
    $('#summary-line').textContent = `${state.profiles.length} profiles, ${summary.model_count ?? 0} models, ${summary.legacy_portability_issue_count ?? 0} portability issues.`;
  } else if (dest === 'console') {
    const profile = getSelectedProfile();
    $('#summary-line').textContent = profile
      ? `${profile.name || profile.mode} — fit and start`
      : DESTINATIONS.console.summary;
  }
}

// The Needs setup metric filters the Profiles table down to the items that
// need attention. It is a control, so it answers to the keyboard as well as
// the pointer (role/tabindex live on the element in index.html).
export function showProfilesNeedingSetup() {
  state.profileFilter = 'setup';
  // Also unhide unavailable so the user actually sees the problems.
  state.hideUnavailableProfiles = false;
  const toggle = $('#hide-unavailable-profiles');
  if (toggle) toggle.checked = false;
  renderProfiles();
  showPanel('profiles');
}

// Queried on call rather than at module scope. A module-scope DOM read works
// in the browser (modules run after parsing) but makes this file -- and every
// module that imports it -- unimportable under node, which the tests need.
export function initSetupWrapper() {
  const wrapper = $('#metric-setup-wrapper');
  if (!wrapper) return;
  wrapper.addEventListener('click', showProfilesNeedingSetup);
  wrapper.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    showProfilesNeedingSetup();
  });
}

export function renderStageFirstRun() {
  const card = $('#stage-first-run');
  const formPanel = $('#parameters');
  if (!card) return;
  const copy = stageFirstRunCopy({
    profileCount: (state.profiles || []).length,
    modelCount: (state.inventory?.models || []).length,
    launchable: (state.profiles || []).some((profile) => profile.launchable),
  });
  if (!copy) {
    card.hidden = true;
    card.innerHTML = '';
    if (formPanel) formPanel.hidden = false;
    return;
  }
  card.hidden = false;
  card.className = 'empty-state empty-state-stage';
  card.innerHTML = emptyStateInner(copy);
  if (formPanel) formPanel.hidden = !(state.profiles || []).length;
}

export function renderIssues() {
  // Legacy combined feed for small lists (kept for compatibility).
  const profileIssues = state.profiles
    .filter((profile) => !profile.launchable || profile.warnings?.length)
    .slice(0, 5)
    .map((profile) => ({
      title: profile.mode,
      text: [...(profile.missing || []), ...(profile.warnings || [])].join(' | ') || 'Needs setup',
      kind: profile.launchable ? 'warn' : 'error',
    }));
  const portability = (state.inventory?.portability_issues || []).slice(0, 5).map((issue) => ({
    title: issue.file?.split(/[\\/]/).slice(-1)[0] || 'Portability issue',
    text: `Line ${issue.line}: ${issue.value}`,
    kind: 'warn',
  }));
  const issues = [...profileIssues, ...portability].slice(0, 8);
  $('#issue-list').innerHTML = issues.map((issue) => `
    <article class="issue-item">
      <span class="badge ${issue.kind === 'error' ? 'error' : 'warn'}">${issue.kind === 'error' ? 'Needs setup' : 'Review'}</span>
      <strong>${escapeHtml(issue.title)}</strong>
      <p>${escapeHtml(issue.text)}</p>
    </article>
  `).join('') || '<div class="empty-state">No setup issues detected.</div>';
}

export function renderPortability() {
  // Richer view for the reworked Portability & Paths panel.
  const summaryEl = $('#portability-summary');
  if (!summaryEl) return;
  const inv = state.inventory || {};
  const roots = (inv.scan_roots || []).map((r) => escapeHtml(r)).join('<br>') || 'Using defaults';
  const cfg = state.config || {};
  const rtRoots = (cfg.runtime_dirs && cfg.runtime_dirs.length ? cfg.runtime_dirs : (inv.runtime_dirs || [])).map((r) => escapeHtml(r)).join('<br>') || 'Auto (PATH + detected)';
  const issueCount = (inv.portability_issues || []).length + state.profiles.filter((p) => !p.launchable).length;
  summaryEl.innerHTML = `
    <div class="portability-roots">
      <div><strong>Model scan roots</strong><br><span class="mono">${roots}</span></div>
      <div><strong>Runtime search</strong><br><span class="mono">${rtRoots}</span></div>
      <div><strong>Issues surfaced</strong><br><span class="badge ${issueCount ? 'warn' : 'ok'}">${issueCount}</span></div>
    </div>
  `;
  // Also refresh the compact issue list underneath
  renderIssues();
}

// ----- Global model rescan --------------------------------------------------
// Registration otherwise runs only at app startup, so a model dropped into a
// scan root mid-session stays invisible until a restart. Distinct from
// #portability-rescan, which rebuilds the inventory and its warnings.
export async function rescanModels(trigger) {
  await withBusy(trigger, async () => {
    try {
      const result = await api('/api/profiles/scan', { method: 'POST', body: JSON.stringify({}) });
      const count = result.registered_count || 0;
      toast(count
        ? `Registered ${count} new profile${count === 1 ? '' : 's'}`
        : 'Rescanned - no new models found');
      await refresh();
    } catch (error) {
      toast(`Rescan failed: ${error.message}`);
    }
  });
}

export function initModelsRescan() {
  const button = document.getElementById('models-rescan');
  if (!button) return;
  button.addEventListener('click', (event) => rescanModels(event.currentTarget));
}
