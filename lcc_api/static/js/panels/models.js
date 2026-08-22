// Models panel.

import { getSelectedProfile, renderProfiles, setSelectedProfileMode, statusBadge } from './profiles.js';
import { renderParameters } from './parameters.js';
import { renderStageFirstRun } from './inventory.js';
import { applyTuneSuggestion, runAutoTune, runFitTest } from './fit.js';
import { $, dirname, escapeHtml, formatBytes } from '../util.js';
import { state } from '../state.js';
import { openSettings } from '../settings.js';
import { showPanel } from '../router.js';
import { refresh } from '../refresh.js';
import { modelMatches, profileForModelPath } from '../matching.js';
import { confirmAction, toast, withBusy } from '../feedback.js';
import { emptyStateHtml, modelsEmptyCopy } from '../copy.js';
import { api } from '../api.js';

// Model Notes keeps HF info, fit-test, and benchmark results in separate slots
// so running a benchmark no longer wipes the fit recommendation (and vice
// versa); each is rendered in its own titled block, clearly separated.
export const MODEL_NOTE_TITLES = { hf: 'Hugging Face', tune: 'Smart fit', sampling: 'Sampling preset', fit: 'Fit test', benchmark: 'Benchmark' };

export function setModelNote(slot, html) {
  state.modelNotes[slot] = html || '';
  const present = Object.keys(MODEL_NOTE_TITLES).filter((key) => state.modelNotes[key]);
  $('#model-info-box').innerHTML = present.length
    ? present.map((key) => `<div class="note-block"><h3 class="note-block-title">${MODEL_NOTE_TITLES[key]}</h3>${state.modelNotes[key]}</div>`).join('')
    : 'Select a profile, then run HF info or Fit test.';
}

export function renderModels() {
  const models = (state.inventory?.models || []).filter(modelMatches);
  $('#model-list').innerHTML = models.map((model) => {
    const profile = profileForModelPath(state.profiles, model.path);
    const actions = profile
      ? `
        <button class="mini-button" type="button" data-model-action="params" data-model-path="${escapeHtml(model.path)}" title="Open this model in the Parameters editor">Parameters</button>
        <button class="mini-button" type="button" data-model-action="fit" data-model-path="${escapeHtml(model.path)}" title="Run a fit test for this model">Fit test</button>
        <button class="mini-button" type="button" data-model-action="tune" data-model-path="${escapeHtml(model.path)}" title="Smart-fit auto-tune this model">Auto-tune</button>
        <button class="mini-button" type="button" data-model-action="hf" data-model-path="${escapeHtml(model.path)}" title="Hugging Face info + update check">HF check</button>`
      : `
        <button class="mini-button primary" type="button" data-model-action="register" data-model-path="${escapeHtml(model.path)}" title="Register this model as a launchable profile">Register</button>`;
    return `
    <article class="model-row">
      <strong>${escapeHtml(model.name)}</strong>
      <div class="model-meta">
        <span class="badge">${escapeHtml(model.quant || 'unknown quant')}</span>
        <span class="badge">${escapeHtml(formatBytes(model.size_bytes))}</span>
        <span class="badge">${escapeHtml(model.source)}</span>
      </div>
      <div class="model-path">${escapeHtml(model.path)}</div>
      <div class="model-actions">${actions}</div>
    </article>`;
  }).join('') || emptyStateHtml(modelsEmptyCopy((state.inventory?.models || []).length, state.query));
  renderStageFirstRun();
}

// Select the profile that owns `path` in the Parameters editor (same code
// path as the #param-profile dropdown), returning the profile or null.
export function selectProfileForModelPath(path) {
  const profile = profileForModelPath(state.profiles, path);
  if (!profile) {
    toast('No profile for this model yet — click Register first');
    return null;
  }
  setSelectedProfileMode(profile.mode);
  const select = $('#param-profile');
  if (select) select.value = profile.mode;
  renderParameters();
  renderProfiles();
  return profile;
}

export async function handleModelAction(action, path, trigger) {
  if (action === 'register') {
    await withBusy(trigger, async () => {
      try {
        const result = await api('/api/profiles/scan', {
          method: 'POST',
          body: JSON.stringify({ model_path: path || '' }),
        });
        toast(result.registered_count
          ? `Registered ${result.registered_count} profile${result.registered_count === 1 ? '' : 's'} for this model`
          : 'No new profile for this model');
        await refresh();
      } catch (error) {
        toast(`Register failed: ${error.message}`);
      }
    });
    return;
  }
  const profile = selectProfileForModelPath(path);
  if (!profile) return;
  if (action === 'params') {
    showPanel('parameters');
  } else if (action === 'fit') {
    await runFitTest();
  } else if (action === 'tune') {
    await runAutoTune();
  } else if (action === 'hf') {
    await fetchHFInfo();
    await checkModelUpdate();
  }
}

export function updateHfCliUi(hfData) {
  const statusBadge = $('#hf-cli-status');
  const versionEl = $('#hf-cli-version');
  const pathEl = $('#hf-cli-path');
  if (!hfData) return;
  if (hfData.installed) {
    statusBadge.textContent = 'Installed';
    statusBadge.className = 'badge ok';
  } else {
    statusBadge.textContent = 'Not installed';
    statusBadge.className = 'badge warn';
  }
  versionEl.textContent = hfData.version || '-';
  pathEl.textContent = hfData.binary_path || '-';
}

export async function suggestDraftModels() {
  const trigger = $('#suggest-draft-button');
  const container = $('#draft-suggestions');
  const profile = getSelectedProfile();
  if (!profile) return;
  await withBusy(trigger, async () => {
    try {
      // api() is a thin fetch wrapper with no query-string support, so the
      // model name has to be encoded into the path (same as checkPortNow).
      const qs = `model_name=${encodeURIComponent(profile.model?.name || '')}`;
      const result = await api(`/api/draft-models/suggest?${qs}`);
      const suggestions = result.suggestions || [];
      if (suggestions.length === 0) {
        container.innerHTML = '<div class="empty-state">No draft model suggestions available for this model.</div>';
        container.hidden = false;
        return;
      }
      container.innerHTML = suggestions.map((s, idx) => `
        <div class="draft-suggestion-item">
          <div>
            <div class="draft-name">${escapeHtml(s.name)}</div>
            <div class="draft-desc">${escapeHtml(s.description || '')} · ${escapeHtml(s.recommended_quant || 'Q4_K_M')}</div>
          </div>
          <button class="mini-button" type="button" data-draft-idx="${idx}" data-draft-repo="${escapeHtml(s.repo_id || '')}">Pull</button>
        </div>
      `).join('');
      container.hidden = false;
      container.querySelectorAll('[data-draft-idx]').forEach((btn) => {
        btn.addEventListener('click', async (event) => {
          const repoId = event.target.dataset.draftRepo;
          await pullDraftModel(repoId, event.target);
        });
      });
    } catch (error) {
      toast(`Draft suggestions failed: ${error.message}`);
    }
  });
}

export async function pullDraftModel(repoId, trigger) {
  const container = $('#draft-suggestions');
  const originalText = trigger.textContent;
  trigger.textContent = 'Pulling...';
  trigger.disabled = true;
  try {
    const result = await api('/api/draft-models/pull', {
      method: 'POST',
      body: JSON.stringify({ repo_id: repoId, quant: 'Q4_K_M' }),
    });
    if (result.success) {
      toast(`Draft model pulled from ${repoId}`);
      container.innerHTML = `<div class="draft-suggestion-item"><div><div class="draft-name">Pulled!</div><div class="draft-desc">${escapeHtml(result.message)}</div></div></div>`;
    } else {
      toast(result.message || 'Pull failed');
    }
  } catch (error) {
    toast(`Pull failed: ${error.message}`);
  } finally {
    trigger.textContent = originalText;
    trigger.disabled = false;
  }
}

export async function fetchHFInfo() {
  const profile = getSelectedProfile();
  if (!profile) return;
  const trigger = $('#hf-info-button');
  setModelNote('hf', 'Fetching Hugging Face metadata...');
  await withBusy(trigger, async () => {
    try {
      const result = await api('/api/models/hf-info', {
        method: 'POST',
        body: JSON.stringify({
          name: profile.model?.name || profile.name,
          path: profile.model?.path || '',
        }),
      });
      const lines = [
        `<strong>${escapeHtml(result.model_id || 'Hugging Face model')}</strong>`,
        result.url ? escapeHtml(result.url) : '',
        result.summary ? escapeHtml(result.summary) : 'No model-card summary found.',
        '',
        `Downloads: ${escapeHtml(result.downloads ?? '-')}`,
        `Likes: ${escapeHtml(result.likes ?? '-')}`,
        `Tags: ${escapeHtml((result.tags || []).slice(0, 8).join(', ') || '-')}`,
      ].filter(Boolean).join('\n');
      setModelNote('hf', lines);
      toast('HF info loaded');
    } catch (error) {
      setModelNote('hf', `<strong>HF lookup failed</strong>\n${escapeHtml(error.message)}`);
      toast(`HF lookup failed: ${error.message}`);
    }
  });
}

export async function checkModelUpdate() {
  const profile = getSelectedProfile();
  if (!profile) return;
  const path = profile.model?.path || '';
  const trigger = $('#hf-update-button');
  setModelNote('hf', 'Checking Hugging Face for a newer copy...');
  await withBusy(trigger, async () => {
    try {
      const result = await api('/api/models/hf-update-check', {
        method: 'POST',
        body: JSON.stringify({ name: profile.model?.name || profile.name, path }),
      });
      const lines = [
        `<strong>${escapeHtml(result.model_id || 'Hugging Face model')}</strong>`,
        result.url ? escapeHtml(result.url) : '',
        result.confident ? '' : 'Matched by search — verify this is the right repo before downloading.',
        result.update_available ? `⚠ Update available — ${escapeHtml(result.reason)}` : `✓ ${escapeHtml(result.reason)}`,
        result.last_modified ? `Repo last modified: ${escapeHtml(result.last_modified)}` : '',
      ];
      // Offer a targeted re-download only when we found the exact file remotely
      // and know where the local copy lives.
      const dest = dirname(path);
      if (result.update_available && result.remote_file?.rfilename && dest) {
        lines.push(
          `<button class="mini-button" type="button" data-action="download-model"`
          + ` data-repo="${escapeHtml(result.model_id)}"`
          + ` data-file="${escapeHtml(result.remote_file.rfilename)}"`
          + ` data-dest="${escapeHtml(dest)}">Download latest into ${escapeHtml(dest)}</button>`,
        );
      }
      setModelNote('hf', lines.filter(Boolean).join('\n'));
      toast(result.update_available ? 'HF update available' : 'Model is up to date');
    } catch (error) {
      setModelNote('hf', `<strong>HF update check failed</strong>\n${escapeHtml(error.message)}`);
      toast(`HF update check failed: ${error.message}`);
    }
  });
}

export function listedHfFiles(data) {
  const raw = Array.isArray(data?.files) ? data.files : [];
  const names = raw.map((item) => String(item || '').replace(/\\/g, '/').trim()).filter(Boolean);
  const gguf = names.filter((name) => /\.gguf$/i.test(name));
  return gguf.length ? gguf : names;
}

export async function searchHfBrowser() {
  const input = $('#hf-search-input');
  const q = (input.value || '').trim();
  const resEl = $('#hf-browser-results');
  if (!q || !resEl) return;
  resEl.innerHTML = '<div class="loading">Fetching info…</div>';
  try {
    const data = await api('/api/models/hf-info', {
      method: 'POST',
      body: JSON.stringify({ repo_id: q }),
    });
    if (!data.success) {
      resEl.innerHTML = emptyStateHtml({
        title: 'No repo found',
        body: data.error || 'Hugging Face did not return a model card for that id.',
      });
      return;
    }
    const files = listedHfFiles(data);
    let html = `<strong>${escapeHtml(data.model_id || q)}</strong><br>`;
    html += `Downloads: ${data.downloads || '–'} · Likes: ${data.likes || '–'}<br>`;
    if (data.summary) html += `<small>${escapeHtml(String(data.summary).slice(0, 120))}</small><br>`;
    if (!files.length) {
      html += emptyStateHtml({
        title: 'No downloadable files listed',
        body: 'This repo did not publish filenames. Open it on Hugging Face instead of guessing a quant.',
      });
    } else {
      html += '<div class="hf-file-list">';
      files.slice(0, 40).forEach((file) => {
        html += `<div class="hf-file-row"><span>${escapeHtml(file)}</span> <button class="mini-button" type="button" data-hf-repo="${escapeHtml(data.model_id || q)}" data-hf-file="${escapeHtml(file)}">Download</button></div>`;
      });
      html += '</div>';
    }
    resEl.innerHTML = html;

    resEl.querySelectorAll('button[data-hf-repo]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const dest = (state.inventory?.scan_roots || [])[0] || '';
        if (!dest) {
          toast('Add a model folder in Settings before downloading.');
          openSettings({ focus: 'model-dirs' });
          return;
        }
        await downloadModelUpdate(btn.dataset.hfRepo, btn.dataset.hfFile, dest, btn);
      });
    });
  } catch (err) {
    resEl.innerHTML = emptyStateHtml({
      title: 'Hugging Face lookup failed',
      body: err.message || 'The request did not complete.',
    });
  }
}

export async function downloadModelUpdate(repo, file, dest, trigger) {
  if (!repo || !file || !dest) {
    toast('Need a repo, filename, and destination folder.');
    return;
  }
  const confirmed = await confirmAction({
    title: 'Download model file',
    message: `Write ${file} from ${repo} into ${dest}. If that filename is already there, it will be replaced.`,
    confirmLabel: 'Download',
  });
  if (!confirmed) return;
  await withBusy(trigger, async () => {
    try {
      const result = await api('/api/models/hf-download', {
        method: 'POST',
        body: JSON.stringify({ repo_id: repo, filename: file, dest_dir: dest }),
      });
      toast(result.message || 'Download complete');
    } catch (error) {
      toast(`Download failed: ${error.message}`);
    }
  });
}

// Event wiring for this panel, moved out of app.js's wireEvents().
export function initModelsPanel() {
  $('#model-info-box').addEventListener('click', (event) => {
    const button = event.target.closest('[data-tune-index]');
    if (button) applyTuneSuggestion(Number(button.dataset.tuneIndex));
  });
  $('#model-list').addEventListener('click', (event) => {
    const button = event.target.closest('[data-model-action]');
    if (!button) return;
    handleModelAction(button.dataset.modelAction, button.dataset.modelPath, button);
  });
  $('#hf-info-button').addEventListener('click', fetchHFInfo);
  $('#hf-update-button').addEventListener('click', checkModelUpdate);
  $('#hf-check-updates-button').addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    const trigger = $('#hf-check-updates-button');
    withBusy(trigger, async () => {
      try {
        const result = await api('/api/hf-cli/check-updates', { method: 'POST' });
        if (result.needs_update) {
          toast('Hugging Face CLI update available');
        } else {
          toast('Hugging Face CLI is up to date');
        }
      } catch (error) {
        toast(`Update check failed: ${error.message}`);
      }
    });
  });
  $('#hf-search-btn')?.addEventListener('click', searchHfBrowser);
  $('#hf-search-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') searchHfBrowser();
  });
  $('#suggest-draft-button').addEventListener('click', suggestDraftModels);
}
