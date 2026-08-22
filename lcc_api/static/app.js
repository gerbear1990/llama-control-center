// Llama Control Center -- entry point.
// Shared code lives in ./js/; this file wires it together and boots.

import { api } from './js/api.js';
import { toast, withBusy, promptProfileDetails, hideFloatingTooltip, enhanceTooltips, trapTab } from './js/feedback.js';
import { serverUrl } from './js/launch.js';
import { wireToolsMenu } from './js/menus.js';
import { hideCommandPalette, initPalette, paletteVisible, registerCommands, showCommandPalette } from './js/palette.js';
import { clearChat, initChatPanel, restoreChatHistory, sendTestPrompt } from './js/panels/chat.js';
import { applySamplingPreset, applyTuneSuggestion, initFitPanel, loadSamplingPresets, runAutoTune, runBenchmark, runFitTest, scheduleTpsEstimate } from './js/panels/fit.js';
import { startLiveHardwarePolling } from './js/panels/hardware.js';
import { initSetupWrapper, initModelsRescan } from './js/panels/inventory.js';
import { initLogFollow, initLogsPanel, loadLogs } from './js/panels/logs.js';
import { checkModelUpdate, downloadModelUpdate, fetchHFInfo, handleModelAction, initModelsPanel, renderModels, searchHfBrowser, suggestDraftModels } from './js/panels/models.js';
import { clearParamOverrides, collectOverrides, initParametersPanel, numericValue, renderParameters, restoreParamOverrides, saveCurrentOverrides, schedulePortCheck, selectedMode } from './js/panels/parameters.js';
import { clearProfileFilters, createNewProfile, initProfilesPanel, openProfileMenu, profileLabel, renderProfiles, requireSelectedProfile, saveProfileAsCopy, saveProfileName, serverRunningForMode, setSelectedProfileMode, toggleGroup } from './js/panels/profiles.js';
import { initRuntimesPanel, recheckRuntime, refreshRuntimeUpdates, renderRuntimes } from './js/panels/runtimes.js';
import { initServersPanel, prepareProfile, purgeServers, restartTracked, startProfile, startServerPolling, stopProfileByMode, stopTracked } from './js/panels/servers.js';
import { refresh } from './js/refresh.js';
import { showDestination, showPanel, applyHashRoute, enhancePanels, enhanceSidebar, syncSearchInputs, persistDisclosure } from './js/router.js';
import { closeSettings, detectedRuntimeRoots, exportPortableConfig, initSettings, openSettings, saveSettings } from './js/settings.js';
import { state } from './js/state.js';
import { applyTheme, cycleTheme, darkMediaQuery, initTheme } from './js/theme.js';
import { $, $$, listToLines } from './js/util.js';

initSetupWrapper();




































































































// Every entry reuses the same code path as the button that already does the
// job, confirm modals included — the palette is a second door, not a bypass.
const COMMAND_REGISTRY = {
  'focus-search': () => {
    const s = $('#search-input');
    if (s) { s.focus(); s.select(); }
  },
  'open-settings': () => openSettings(),
  'refresh': () => { refresh(); },
  'start-profile': () => {
    const profile = requireSelectedProfile();
    if (profile) startProfile(profile.mode, $('#start-selected-button'));
  },
  'stop-profile': () => {
    const profile = requireSelectedProfile();
    if (profile) stopProfileByMode(profile.mode, $('#stop-selected-button'));
  },
  'restart-profile': () => {
    const profile = requireSelectedProfile();
    if (!profile) return;
    const tracked = (state.servers || []).find((server) => server.mode === profile.mode);
    if (!tracked) {
      toast(`No tracked server for "${profileLabel(profile.mode)}" to restart`);
      return;
    }
    restartTracked(tracked.id, null);
  },
  'smart-fit': () => {
    if (requireSelectedProfile()) runAutoTune();
  },
  'fit-test': () => {
    if (requireSelectedProfile()) runFitTest();
  },
  'benchmark': () => {
    if (requireSelectedProfile()) runBenchmark();
  },
  'open-logs': () => {
    const serverId = state.selectedServerId || state.servers[0]?.id;
    if (!serverId) {
      toast('No tracked server to open logs for');
      return;
    }
    loadLogs(serverId);
    showPanel('logs');
  },
  'purge-stopped': () => { purgeServers(true, $('#servers-purge-stopped')); },
  'toggle-theme': () => cycleTheme(),
  'new-profile': () => createNewProfile($('#new-profile-button')),
  'save-profile-copy': () => {
    const profile = requireSelectedProfile();
    if (!profile) return;
    if (!profile.launchable) {
      toast('Selected profile is not launchable; nothing to copy');
      return;
    }
    saveProfileAsCopy(profile);
  },
};

registerCommands(COMMAND_REGISTRY);
































































function wireEvents() {
  applyTheme();
  enhanceTooltips();
  $('#api-copy')?.addEventListener('click', () => {
    const details = $('#api-copy')?.dataset.details;
    if (!details) return;
    navigator.clipboard.writeText(details).then(() => toast('API status copied to clipboard'));
  });
  persistDisclosure($('#param-sampling-disclosure'), 'lcc-params-sampling');
  persistDisclosure($('#param-advanced-disclosure'), 'lcc-params-advanced');
  enhancePanels();
  enhanceSidebar();
  wireToolsMenu();
  // Enable layout transitions only after the initial collapsed state is painted,
  // so panels and the sidebar don't animate from open→closed on first load.
  requestAnimationFrame(() => $('.app-shell').classList.add('anim-ready'));
  $('#refresh-button').addEventListener('click', refresh);
  // While following the system, an OS-level switch has to land immediately.
  $('#search-input').addEventListener('input', (event) => {
    state.query = event.target.value;
    syncSearchInputs(state.query);
    renderProfiles();
    renderModels();
  });
  document.body.addEventListener('click', (event) => {
    const launchAction = event.target.closest('[data-launch-action]');
    if (launchAction) {
      const act = launchAction.dataset.launchAction;
      if (act === 'copy') {
        const url = serverUrl(serverRunningForMode(selectedMode()));
        if (!url) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(url).then(() => toast(`Copied ${url}`));
        } else {
          toast(url);
        }
      } else if (act === 'chat') {
        showPanel('chat');
      }
      return;
    }
    const emptyAction = event.target.closest('[data-empty-action]');
    if (emptyAction) {
      const act = emptyAction.dataset.emptyAction;
      if (act === 'add-folders') openSettings({ focus: 'model-dirs' });
      else if (act === 'add-runtime-folders') openSettings({ focus: 'runtime-dirs' });
      else if (act === 'clear-filters') clearProfileFilters();
      else if (act === 'goto-models') showPanel('models');
      else if (act === 'goto-inventory') showDestination('inventory');
      else if (act === 'goto-stage') showPanel('parameters');
      else if (act === 'show-all-runtimes') {
        state.hideNotInstalledRuntimes = false;
        localStorage.setItem('lcc-hide-not-installed-runtimes', '0');
        const toggle = $('#hide-not-installed-runtimes');
        if (toggle) toggle.checked = false;
        renderRuntimes();
      }
      return;
    }
    // Server selection (clicking the card itself, not action buttons inside)
    const serverCard = event.target.closest('.server-item');
    if (serverCard && !event.target.closest('button')) {
      const sid = serverCard.dataset.serverId;
      if (sid) {
        state.selectedServerId = sid;
        const server = (state.servers || []).find(s => s.id === sid);
        // Selecting a server selects its profile too, so the chat transcript,
        // the parameter form and the highlighted row all describe one thing.
        if (server?.mode && state.profiles.some((profile) => profile.mode === server.mode)) {
          if (setSelectedProfileMode(server.mode)) {
            renderParameters();
            renderProfiles();
          }
        }
        $$('.server-item').forEach((el) => {
          const on = el.dataset.serverId === sid;
          el.classList.toggle('selected', on);
          el.setAttribute('aria-selected', String(on));
        });
        if ($('.main')?.dataset.session === 'logs') {
          loadLogs(sid, null, { silent: true });
        }
      }
    }

    const target = event.target.closest('button');
    if (!target) return;
    const { action, mode, serverId, runtime, repo, file, dest } = target.dataset;
    if (mode && state.profiles.some((profile) => profile.mode === mode)) {
      if (setSelectedProfileMode(mode)) renderParameters();
    }
    if (action === 'download-model') downloadModelUpdate(repo, file, dest, target);
    else if (action === 'toggle-runtimes') {
      state.showAllRuntimes = !state.showAllRuntimes;
      renderRuntimes();
    }
    else if (action === 'recheck-runtime') recheckRuntime(runtime, target);
    else if (action === 'prepare') prepareProfile(mode, target);
    else if (action === 'start') startProfile(mode, target);
    else if (action === 'logs') loadLogs(serverId, target);
    else if (action === 'restart') {
      if (serverId) restartTracked(serverId, target);
    }
    else if (action === 'stop') {
      if (serverId) stopTracked(serverId, target);
      else if (mode) stopProfileByMode(mode, target);
    }
    else if (action === 'profile-menu') openProfileMenu(target, mode);
    else if (action === 'rename') {
      const profile = state.profiles.find((p) => p.mode === mode);
      if (profile) saveProfileName(mode, profile.name || profile.mode);
    }
  });
  // Portability reworked panel actions
  // Click (or Enter/Space) on the dot forces an immediate re-probe, bypassing
  // the debounce. It is exposed as a button, so both paths have to work.
  // Preset picker writes into #param-ctx (the source of truth), then resets so it
  // always reads "Presets" and never filters its options by the current value.
  document.addEventListener('keydown', (event) => {
    // AC3: Check Ctrl+Shift+K (more specific) BEFORE plain Ctrl+K so palette trigger works
    if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if (paletteVisible) hideCommandPalette(); else showCommandPalette();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if ($('.main')?.dataset.destination !== 'inventory') showDestination('inventory');
      const search = $('#search-input');
      search?.focus();
      search?.select();
      return;
    }
    if (event.key === 'Escape') {
      if (!$('#settings-modal').hidden) {
        closeSettings();
        return;
      }
      if (paletteVisible) {
        hideCommandPalette();
        return;
      }
    }
    if (!$('#settings-modal').hidden) {
      trapTab(event, $('.settings-dialog'));
    }
  });
  window.addEventListener('resize', hideFloatingTooltip);
  window.addEventListener('scroll', hideFloatingTooltip, true);
  $$('.nav-item[data-destination]').forEach((item) => {
    item.addEventListener('click', (event) => {
      event.preventDefault();
      showDestination(item.dataset.destination, item.dataset.destination === 'console' ? 'stage' : undefined);
    });
  });
  $$('.session-tab').forEach((tab) => {
    tab.addEventListener('click', () => showDestination('console', tab.dataset.session));
  });
  window.addEventListener('hashchange', applyHashRoute);
  applyHashRoute();

  // Each panel wires its own listeners.
  initRuntimesPanel();
  initSettings();
  initPalette();
  initTheme();
  initProfilesPanel();
  initServersPanel();
  initLogsPanel();
  initParametersPanel();
  initFitPanel();
  initModelsPanel();
  initChatPanel();
}






























restoreParamOverrides();
restoreChatHistory();
wireEvents();
loadSamplingPresets();
refresh();
startServerPolling();
startLiveHardwarePolling();









initLogFollow();
initModelsRescan();
