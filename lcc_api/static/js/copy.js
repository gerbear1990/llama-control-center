import { escapeHtml } from './util.js';
import { serverEndpoint } from './launch.js';

// Empty-state and first-run copy. Pure: takes counts, returns
// {title, body, action, actionLabel} or null.

export function profilesEmptyCopy(total, filtering, modelCount = 0) {
  if (!total && !modelCount) {
    return {
      title: 'No profiles yet',
      body: 'Add the folders where your GGUF files live. LCC discovers them, you register a profile, then Start from Console.',
      action: 'add-folders',
      actionLabel: 'Add model folders',
    };
  }
  if (!total && modelCount) {
    return {
      title: 'Models found, no profiles',
      body: 'Register a discovered model to create a launch config. Then Start it from Console.',
      action: 'goto-models',
      actionLabel: 'Register a model',
    };
  }
  if (filtering) {
    return {
      title: 'No profiles match this filter',
      body: 'Clear the search, model filter, or “Hide unavailable” to see the full list.',
      action: 'clear-filters',
      actionLabel: 'Show all profiles',
    };
  }
  return null;
}

export function modelsEmptyCopy(total, query) {
  const q = String(query || '').trim();
  if (!total) {
    return {
      title: 'No model files found',
      body: 'LCC only lists GGUF files inside your scan folders. Add a folder, then refresh.',
      action: 'add-folders',
      actionLabel: 'Add model folders',
    };
  }
  if (q) {
    return {
      title: `No models match “${q}”`,
      body: 'Try another name, or clear search to see every discovered file.',
      action: 'clear-filters',
      actionLabel: 'Clear search',
    };
  }
  return {
    title: 'No models match the current search',
    body: 'Clear search to see every discovered file.',
    action: 'clear-filters',
    actionLabel: 'Clear search',
  };
}

export function runtimesEmptyCopy(total, hidingMissing) {
  if (!total) {
    return {
      title: 'No runtimes detected',
      body: 'LCC looks on PATH and in your runtime folders for llama.cpp and friends. Add a folder if the binary is not on PATH.',
      action: 'add-runtime-folders',
      actionLabel: 'Add runtime folders',
    };
  }
  if (hidingMissing) {
    return {
      title: 'No installed runtimes to show',
      body: 'Hidden because “Hide not installed” is on.',
      action: 'show-all-runtimes',
      actionLabel: 'Show all runtimes',
    };
  }
  return null;
}

export function stageFirstRunCopy({ profileCount, modelCount, launchable }) {
  if (!profileCount && !modelCount) {
    return {
      title: 'Add your model folders',
      body: 'Nothing is scanned until you name a folder. Then register a profile and Start from this stage.',
      action: 'add-folders',
      actionLabel: 'Add model folders',
    };
  }
  if (!profileCount && modelCount) {
    return {
      title: 'Register a model to launch',
      body: `${modelCount} model file${modelCount === 1 ? '' : 's'} found. Register one as a profile, then Start here.`,
      action: 'goto-models',
      actionLabel: 'Register a model',
    };
  }
  if (profileCount && !launchable) {
    return {
      title: 'No launchable profiles',
      body: 'A profile is here but its model file or runtime is missing. Add folders or open Inventory to see what needs setup.',
      action: 'add-folders',
      actionLabel: 'Add model folders',
      secondaryAction: 'goto-inventory',
      secondaryLabel: 'Open Inventory',
    };
  }
  return null;
}

export function chatEmptyCopy(running, server) {
  if (!running) {
    return {
      title: 'No running server',
      body: 'Start the selected profile from the Stage. Chat talks to that server.',
      action: 'goto-stage',
      actionLabel: 'Go to Stage',
    };
  }
  const endpoint = serverEndpoint(server);
  return {
    title: 'No messages yet',
    body: endpoint
      ? `Send a prompt to ${endpoint}. Enter sends. Shift+Enter is a new line.`
      : 'Send a prompt to the running server. Enter sends. Shift+Enter is a new line.',
  };
}

export function logsEmptyCopy() {
  return {
    title: 'No server selected',
    body: 'Start a profile from the Stage. Its output lands here.',
    action: 'goto-stage',
    actionLabel: 'Go to Stage',
  };
}

export function serversEmptyCopy() {
  return {
    title: 'No tracked servers',
    body: 'Start a launchable profile. Tracked servers show up here so you can stop them and read logs.',
    action: 'goto-stage',
    actionLabel: 'Go to Stage',
  };
}

export function emptyStateInner(copy) {
  const title = copy.title ? `<strong>${escapeHtml(copy.title)}</strong>` : '';
  const body = copy.body ? `<p>${escapeHtml(copy.body)}</p>` : '';
  const primary = ['add-folders', 'goto-models', 'goto-stage'].includes(copy.action);
  const action = copy.action
    ? `<button class="mini-button${primary ? ' primary' : ''}" type="button" data-empty-action="${escapeHtml(copy.action)}">${escapeHtml(copy.actionLabel)}</button>`
    : '';
  const secondary = copy.secondaryAction
    ? `<button class="mini-button" type="button" data-empty-action="${escapeHtml(copy.secondaryAction)}">${escapeHtml(copy.secondaryLabel)}</button>`
    : '';
  const actions = (action || secondary) ? `<div class="empty-state-actions">${action}${secondary}</div>` : '';
  return `${title}${body}${actions}`;
}

export function emptyStateHtml(copy, { tableCell = false } = {}) {
  if (!copy) return '';
  const inner = `<div class="empty-state">${emptyStateInner(copy)}</div>`;
  return tableCell ? `<tr><td colspan="6">${inner}</td></tr>` : inner;
}
