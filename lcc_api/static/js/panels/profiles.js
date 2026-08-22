// Profiles panel.

import { collectOverrides, getProfileParams, paramDefaults, renderParameters, selectedMode } from './parameters.js';
import { renderModels } from './models.js';
import { renderStageFirstRun } from './inventory.js';
import { renderChatLog } from './chat.js';
import { $, escapeHtml } from '../util.js';
import { state } from '../state.js';
import { openSettings } from '../settings.js';
import { DESTINATIONS, showPanel, syncSearchInputs } from '../router.js';
import { refresh } from '../refresh.js';
import { showPopupMenu } from '../menus.js';
import { profileForModelPath, profileMatches } from '../matching.js';
import { serverEndpoint } from '../launch.js';
import { fitStatusClass, fitStatusLabel } from '../format.js';
import { confirmAction, promptProfileDetails, toast, trapTab, withBusy } from '../feedback.js';
import { emptyStateHtml, profilesEmptyCopy } from '../copy.js';
import { api } from '../api.js';

export function getSelectedProfile() {
  return state.profiles.find((profile) => profile.mode === state.selectedProfileMode) || state.profiles[0] || null;
}

// Human-readable name for a mode slug, for confirms and toasts. Falls back to
// the slug when the profile is gone (deleted, or not loaded yet).
export function profileLabel(mode) {
  const profile = (state.profiles || []).find((item) => item.mode === mode);
  return profile?.name || mode || '';
}

// The single write path for the selected profile. Chat transcripts are stored
// per mode, so every selection change has to repaint #chat-log — otherwise the
// visible transcript belongs to one profile while Send posts to another.
// Returns true when the selection actually moved.
export function consoleSummaryLine() {
  const profile = getSelectedProfile();
  if (!profile) return DESTINATIONS.console.summary;
  const endpoint = serverEndpoint(serverRunningForMode(profile.mode));
  return endpoint
    ? `${profile.name || profile.mode} — listening on ${endpoint}`
    : `${profile.name || profile.mode} — fit and start`;
}

export function setSelectedProfileMode(mode) {
  const next = mode || null;
  if (state.selectedProfileMode === next) return false;
  state.selectedProfileMode = next;
  renderChatLog(next);
  if ($('.main')?.dataset.destination === 'console') {
    const summary = $('#summary-line');
    if (summary) summary.textContent = consoleSummaryLine();
  }
  return true;
}

export function serverRunningForMode(mode) {
  const server = state.servers?.find((s) => s.mode === mode && s.running);
  return server || null;
}

export function statusBadge(profile) {
  if (profile.launchable) return '<span class="badge ok">Launchable</span>';
  return '<span class="badge warn">Needs setup</span>';
}

export function profileIsUnavailable(profile) {
  return !profile.launchable || !profile.model?.path;
}

export function filteredProfiles() {
  return state.profiles
    .filter((profile) => {
      if (state.profileFilter === 'launchable') return profile.launchable;
      if (state.profileFilter === 'setup') return !profile.launchable;
      return true;
    })
    .filter((profile) => !state.hideUnavailableProfiles || !profileIsUnavailable(profile))
    .filter((profile) => {
      if (!state.profileModelFilter || state.profileModelFilter === 'all') return true;
      return (profile.model?.name || 'Unresolved model') === state.profileModelFilter;
    })
    .filter(profileMatches);
}

export function loadCollapsedGroups() {
  try {
    const stored = localStorage.getItem('lcc-collapsed-groups');
    if (stored) {
      return new Set(JSON.parse(stored));
    }
  } catch { /* ignore */ }
  return new Set();
}

export function saveCollapsedGroups(groups) {
  try {
    localStorage.setItem('lcc-collapsed-groups', JSON.stringify([...groups]));
  } catch { /* ignore */ }
}

export const collapsedGroups = loadCollapsedGroups();

export function groupProfilesByModel(profiles) {
  const groups = {};
  profiles.forEach((profile) => {
    const modelName = profile.model?.name || 'Unresolved model';
    if (!groups[modelName]) {
      groups[modelName] = { model: modelName, profiles: [] };
    }
    groups[modelName].profiles.push(profile);
  });
  return Object.values(groups).sort((a, b) => a.model.localeCompare(b.model));
}

export function toggleGroup(modelName) {
  if (collapsedGroups.has(modelName)) {
    collapsedGroups.delete(modelName);
  } else {
    collapsedGroups.add(modelName);
  }
  saveCollapsedGroups(collapsedGroups);
  renderProfiles();
}

export function shortModelVariant(profile) {
  const name = profile.model?.name || profile.mode || 'Unresolved model';
  const quant = profile.model?.quant;
  if (quant && !name.toLowerCase().includes(String(quant).toLowerCase())) {
    return `${name.split(/[\\/]/).pop()} ${quant}`;
  }
  return name
    .replace(/-gguf$/i, '')
    .replace(/\.gguf$/i, '')
    .replace(/[-_]+/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

export let renderedModelOptions = '';

export function updateProfileToolbar(filteredCount) {
  const filterInput = $('#profile-filter-input');
  if (filterInput && filterInput.value !== state.query) filterInput.value = state.query;
  const modelSelect = $('#profile-model-filter');
  if (modelSelect) {
    const models = Array.from(new Set(state.profiles.map((profile) => profile.model?.name || 'Unresolved model'))).sort((a, b) => a.localeCompare(b));
    if (state.profileModelFilter !== 'all' && !models.includes(state.profileModelFilter)) {
      state.profileModelFilter = 'all';
    }
    // Background repaints run through here, so only rebuild the options when
    // the model set really changed — replacing them would close an open
    // dropdown and drop focus mid-selection.
    const optionsHtml = '<option value="all">All models</option>' + models.map((model) => (
      `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`
    )).join('');
    if (renderedModelOptions !== optionsHtml) {
      modelSelect.innerHTML = optionsHtml;
      renderedModelOptions = optionsHtml;
    }
    modelSelect.value = state.profileModelFilter || 'all';
  }
  const availabilityToggle = $('#hide-unavailable-profiles');
  if (availabilityToggle) availabilityToggle.checked = state.hideUnavailableProfiles;
  const filtering = profileFiltersActive();
  const count = $('#profiles-count');
  if (count) {
    count.textContent = filtering
      ? `Showing ${filteredCount} of ${state.profiles.length} profiles`
      : `${state.profiles.length} profile${state.profiles.length === 1 ? '' : 's'}`;
  }
  // "Show all profiles" only means something while something is hidden.
  const viewAll = $('#view-all-profiles');
  if (viewAll) viewAll.hidden = !filtering;
}

export function profileFiltersActive() {
  return Boolean(
    state.query.trim()
    || state.hideUnavailableProfiles
    || (state.profileFilter && state.profileFilter !== 'all')
    || (state.profileModelFilter && state.profileModelFilter !== 'all'),
  );
}

// The honest version of the old "View all profiles" no-op anchor: drop every
// filter and search term, which is what actually reveals all of them.
export function clearProfileFilters() {
  state.query = '';
  syncSearchInputs('');
  state.profileFilter = 'all';
  state.profileModelFilter = 'all';
  state.hideUnavailableProfiles = false;
  localStorage.setItem('lcc-hide-unavailable-profiles', '0');
  renderProfiles();
  renderModels();
}

export function openRenameDialog(mode, currentName) {
  const modal = $('#rename-modal');
  const input = $('#rename-input');
  const okBtn = $('#rename-ok');
  const cancelBtn = $('#rename-cancel');
  input.value = currentName || mode;
  modal.hidden = false;
  document.body.classList.add('modal-open');
  const priorFocus = document.activeElement;
  input.focus();
  input.select();
  return new Promise((resolve) => {
    function cleanup() {
      modal.hidden = true;
      document.body.classList.remove('modal-open');
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
      modal.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      if (priorFocus && typeof priorFocus.focus === 'function') {
        priorFocus.focus();
      }
    }
    function onOk() { cleanup(); resolve(input.value.trim()); }
    function onCancel() { cleanup(); resolve(null); }
    function onBackdrop(event) { if (event.target === modal) onCancel(); }
    function onKey(event) {
      if (event.key === 'Escape') onCancel();
      else if (event.key === 'Enter') { event.preventDefault(); onOk(); }
      else trapTab(event, modal.querySelector('.rename-dialog'));
    }
    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    modal.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);
  });
}

export async function saveProfileName(mode, currentName) {
  const newName = await openRenameDialog(mode, currentName);
  if (!newName) return;
  try {
    await api('/api/profiles/name', {
      method: 'POST',
      body: JSON.stringify({ mode, name: newName }),
    });
    toast(`Renamed to "${newName}"`);
    await refresh();
  } catch (error) {
    toast(`Failed to save profile name: ${error.message}`);
  }
}

// Open the row context menu for a profile. Triggered by the row's "..." button
// (data-action="profile-menu"). The menu replaces the previous stub that only
// triggered Rename — Delete is gated by a confirm modal and refuses while a
// tracked server is still running (the backend enforces the same rule).
export function openProfileMenu(button, mode) {
  const profile = state.profiles.find((p) => p.mode === mode);
  if (!profile) return;
  const serverRunning = state.servers?.some(
    (server) => server.mode === mode && server.running,
  );
  showPopupMenu(button, [
    {
      label: 'Rename profile…',
      onSelect: () => saveProfileName(mode, profile.name || profile.mode),
    },
    {
      label: 'Save as copy…',
      disabled: !profile.launchable,
      title: profile.launchable
        ? 'Save the current parameters under a new profile name.'
        : 'Profile is not launchable; nothing to copy.',
      onSelect: () => saveProfileAsCopy(profile),
    },
    { separator: true },
    {
      label: 'Delete profile',
      danger: true,
      disabled: serverRunning,
      title: serverRunning
        ? 'A tracked server is still running for this profile. Stop it first.'
        : 'Remove this profile from models.json.',
      onSelect: () => deleteProfileConfirm(mode),
    },
  ]);
}

// Build a manifest ``mode`` from a profile name using the same rule the
// backend applies when it registers a discovered model: every run of
// characters outside [a-zA-Z0-9._-] collapses to a single '-', then trim and
// lowercase. A numeric suffix is appended until the mode is unused.
export function uniqueProfileMode(name, fallback = 'profile') {
  let slug = String(name || '')
    .replace(/[^a-zA-Z0-9._-]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase();
  if (!slug) slug = fallback;
  const taken = new Set((state.profiles || []).map((profile) => profile.mode));
  if (!taken.has(slug)) return slug;
  let suffix = 2;
  while (taken.has(`${slug}-${suffix}`)) suffix += 1;
  return `${slug}-${suffix}`;
}

// Create a new models.json entry with its own mode. Never reuses the selected
// profile's mode — that path is Save parameters, and wiring New to it was the
// overwrite foot-gun. Starter params come from defaults, not the open form.
export async function createNewProfile(trigger) {
  const selected = state.profiles.find((profile) => profile.mode === state.selectedProfileMode) || null;
  const models = state.inventory?.models || [];
  const unregistered = models.find((model) => !profileForModelPath(state.profiles, model.path));
  const modelPath = selected?.model?.path || unregistered?.path || models[0]?.path || '';
  const modelName = selected?.model?.name || unregistered?.name || models[0]?.name || '';
  if (!modelPath) {
    toast('No model file to attach. Add folders in Settings, then try again.');
    openSettings();
    return;
  }
  const result = await promptProfileDetails({
    title: 'New profile',
    okLabel: 'Create profile',
    name: modelName || 'New profile',
    description: '',
    message: `Creates a new launch config for ${modelName || 'this model'}. Existing profiles stay as they are.`,
  });
  if (!result) return;
  const mode = uniqueProfileMode(result.name);
  const params = paramDefaults();
  await withBusy(trigger, async () => {
    try {
      const saveResult = await api('/api/profiles/save', {
        method: 'POST',
        body: JSON.stringify({
          mode,
          name: result.name,
          description: result.description,
          model_path: modelPath,
          params,
        }),
      });
      if (saveResult.success) {
        toast(saveResult.message || `Created "${result.name}"`);
        await refresh();
        setSelectedProfileMode(mode);
        renderParameters();
        renderProfiles();
      } else {
        toast(saveResult.message || 'Could not create profile');
      }
    } catch (error) {
      toast(`Could not create profile: ${error.message}`);
    }
  });
}

// Save the profile's current parameters under a new name. /api/profiles/save
// matches on ``mode``, so a copy has to carry a fresh mode of its own —
// re-posting the source mode would rename the original instead of duplicating
// it. An unknown mode makes the endpoint append a new manifest entry.
export async function saveProfileAsCopy(profile) {
  const result = await promptProfileDetails({
    title: 'Save as copy',
    okLabel: 'Save copy',
    name: `${profile.name || profile.mode} copy`.trim(),
    description: profile.description || '',
    message: `Writes a new profile. "${profile.name || profile.mode}" is left unchanged.`,
  });
  if (!result) return;
  const mode = uniqueProfileMode(result.name, `${profile.mode}-copy`);
  // The parameter form only mirrors the selected profile; for any other row
  // take the params off the profile itself.
  const params = selectedMode() === profile.mode ? collectOverrides() : getProfileParams(profile);
  try {
    const saveResult = await api('/api/profiles/save', {
      method: 'POST',
      body: JSON.stringify({
        mode,
        name: result.name,
        description: result.description,
        model_path: profile.model?.path || '',
        params,
      }),
    });
    if (saveResult.success) {
      toast(saveResult.message || `Saved copy '${result.name}'`);
      await refresh();
    } else {
      toast(saveResult.message || 'Save failed');
    }
  } catch (error) {
    toast(`Save failed: ${error.message}`);
  }
}

export async function deleteProfileConfirm(mode) {
  const profile = state.profiles.find((p) => p.mode === mode);
  const displayName = profile?.name || mode;
  const ok = await confirmAction({
    title: 'Delete profile',
    message: `Delete profile "${displayName}" (${mode})? This removes it from models.json. This cannot be undone.`,
    confirmLabel: 'Delete',
    confirmKind: 'danger',
  });
  if (!ok) return;
  try {
    const result = await api('/api/profiles/delete', {
      method: 'POST',
      body: JSON.stringify({ mode }),
    });
    if (result.success) {
      toast(result.message || `Deleted "${displayName}"`);
      if (state.selectedProfileMode === mode) {
        setSelectedProfileMode(null);
      }
      await refresh();
    } else {
      toast(result.message || 'Delete failed');
    }
  } catch (error) {
    toast(`Delete failed: ${error.message}`);
  }
}

export function renderProfiles() {
  const profiles = filteredProfiles();
  updateProfileToolbar(profiles.length);
  const groupedProfiles = groupProfilesByModel(profiles);
  let html = '';
  groupedProfiles.forEach((group) => {
    const isCollapsed = collapsedGroups.has(group.model);
    html += `
      <tr class="profile-group-header">
        <td colspan="6">
          <button class="group-toggle" type="button" data-model="${escapeHtml(group.model)}" aria-expanded="${String(!isCollapsed)}" aria-label="${isCollapsed ? 'Expand' : 'Collapse'} ${escapeHtml(group.model)}">
            <span aria-hidden="true">${isCollapsed ? '▸' : '▾'}</span>
            <span>${escapeHtml(group.model)}</span>
            <span class="profile-group-count">${group.profiles.length}</span>
          </button>
        </td>
      </tr>
    `;
    if (!isCollapsed) {
      group.profiles.forEach((profile) => {
        const selected = profile.mode === state.selectedProfileMode;
        html += `
          <tr class="profile-row ${selected ? 'selected' : ''}" data-profile-mode="${escapeHtml(profile.mode)}" tabindex="0" aria-selected="${selected ? 'true' : 'false'}">
            <td data-label="Model">
              <div class="cell-title">${escapeHtml(shortModelVariant(profile))}</div>
            </td>
            <td data-label="Profile">
              <div class="cell-title">${escapeHtml(profile.name || profile.mode)}</div>
              <div class="cell-subtitle">${escapeHtml(profile.mode)}</div>
            </td>
            <td data-label="Fit"><span class="badge ${fitStatusClass(profile.fit_status?.status)}">${escapeHtml(fitStatusLabel(profile.fit_status?.status))}</span></td>
            <td data-label="Port"><code>${escapeHtml(profile.params?.port || '—')}</code></td>
            <td data-label="Status">${statusBadge(profile)}</td>
            <td data-label="Actions">
              <div class="row-actions">
                ${serverRunningForMode(profile.mode)
                  ? `<button class="mini-button danger" type="button" data-action="stop" data-mode="${escapeHtml(profile.mode)}" title="Stop server" aria-label="Stop ${escapeHtml(profile.name || profile.mode)}">Stop</button>`
                  : `<button class="mini-button" type="button" data-action="start" data-mode="${escapeHtml(profile.mode)}" ${profile.launchable ? '' : 'disabled'} title="Start server" aria-label="Start ${escapeHtml(profile.name || profile.mode)}">Start</button>`}
                <button class="mini-button icon-button" type="button" data-action="profile-menu" data-mode="${escapeHtml(profile.mode)}" title="More profile actions" aria-label="More profile actions" aria-haspopup="menu" aria-expanded="false">...</button>
              </div>
            </td>
          </tr>
        `;
      });
    }
  });
  $('#profiles-table').innerHTML = html || emptyStateHtml(
    profilesEmptyCopy(state.profiles.length, profileFiltersActive(), (state.inventory?.models || []).length),
    { tableCell: true },
  );
  renderStageFirstRun();
}

// Plain command registry (pure mapping of id -> real shipped handler fn).
// Directly testable; no DOM creation here. Used by palette and shortcuts (AC3).
// Commands that operate on "the selected profile" need one to exist. Returning
// null after a toast keeps every such command a no-op rather than a silent one.
export function requireSelectedProfile() {
  const mode = selectedMode();
  const profile = mode ? state.profiles.find((p) => p.mode === mode) : null;
  if (!profile) {
    toast('Select a profile first');
    return null;
  }
  return profile;
}

// Event wiring for this panel, moved out of app.js's wireEvents().
export function initProfilesPanel() {
  $('#profile-filter-input')?.addEventListener('input', (event) => {
    state.query = event.target.value;
    syncSearchInputs(state.query);
    renderProfiles();
    renderModels();
  });
  $('#profile-model-filter')?.addEventListener('change', (event) => {
    state.profileModelFilter = event.target.value || 'all';
    renderProfiles();
  });
  $('#hide-unavailable-profiles')?.addEventListener('change', (event) => {
    state.hideUnavailableProfiles = event.target.checked;
    localStorage.setItem('lcc-hide-unavailable-profiles', state.hideUnavailableProfiles ? '1' : '0');
    renderProfiles();
  });
  $('#new-profile-button')?.addEventListener('click', (event) => createNewProfile(event.currentTarget));
  $('#profile-menu-button')?.addEventListener('click', () => {
    const mode = state.selectedProfileMode;
    if (!mode) {
      toast('Select a profile row first');
      return;
    }
    const profile = state.profiles.find((p) => p.mode === mode);
    if (!profile) {
      toast('Selected profile not found');
      return;
    }
    if (!profile.launchable) {
      toast('Selected profile is not launchable; nothing to save');
      return;
    }
    saveProfileAsCopy(profile);
  });
  $('#profiles-table').addEventListener('click', (event) => {
    const row = event.target.closest('tr.profile-row');
    if (!row) return;
    if (event.target.closest('button')) return;
    const mode = row.dataset.profileMode;
    if (!mode || !setSelectedProfileMode(mode)) return;
    renderParameters();
    renderProfiles();
  });
  $('#profiles-table').addEventListener('keydown', (event) => {
    const row = event.target.closest('tr.profile-row');
    if (!row || event.target.closest('button')) return;
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    const mode = row.dataset.profileMode;
    if (!mode || !setSelectedProfileMode(mode)) return;
    renderParameters();
    renderProfiles();
  });
  $('#profiles-table').addEventListener('click', (event) => {
    const toggle = event.target.closest('.group-toggle');
    if (toggle) {
      event.stopPropagation();
      toggleGroup(toggle.dataset.model);
      return;
    }
  });
  $('#view-all-profiles')?.addEventListener('click', (event) => {
    event.preventDefault();
    clearProfileFilters();
    showPanel('profiles');
  });
}
