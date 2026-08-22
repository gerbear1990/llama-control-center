// Three-state theme: light, dark, or follow the system.

import { $, escapeHtml } from './util.js';
import { state } from './state.js';

// Theme is a three-state cycle: light -> dark -> system. Only the resolved
// value is ever stamped on the root, so the stylesheet stays two-state.
export const THEME_CYCLE = ['light', 'dark', 'system'];

export const THEME_LABELS = { light: 'Light', dark: 'Dark', system: 'System' };

// Resolved on call, not at module scope: a module-scope window read makes this
// file unimportable under node, and every module that imports it too.
let darkMedia = null;

export function darkMediaQuery() {
  if (!darkMedia && typeof window !== 'undefined' && window.matchMedia) {
    darkMedia = window.matchMedia('(prefers-color-scheme: dark)');
  }
  return darkMedia;
}

export function resolvedTheme() {
  if (state.theme === 'system') return darkMediaQuery()?.matches ? 'dark' : 'light';
  return state.theme === 'dark' ? 'dark' : 'light';
}

export function applyTheme() {
  const mode = THEME_LABELS[state.theme] ? state.theme : 'system';
  const resolved = resolvedTheme();
  document.documentElement.dataset.theme = resolved;
  const button = $('#theme-button');
  if (!button) return;
  const next = THEME_CYCLE[(THEME_CYCLE.indexOf(mode) + 1) % THEME_CYCLE.length];
  const description = mode === 'system'
    ? `Theme: system (following this device, currently ${resolved})`
    : `Theme: ${mode}`;
  button.dataset.themeMode = mode;
  button.innerHTML = `<span class="theme-glyph" aria-hidden="true"></span>${escapeHtml(THEME_LABELS[mode])}`;
  button.setAttribute('title', `${description}. Switch to ${next}.`);
  button.setAttribute('aria-label', `${description}. Switch to ${next}.`);
}

export function cycleTheme() {
  const mode = THEME_LABELS[state.theme] ? state.theme : 'system';
  state.theme = THEME_CYCLE[(THEME_CYCLE.indexOf(mode) + 1) % THEME_CYCLE.length];
  try {
    localStorage.setItem('lcc-theme', state.theme);
  } catch { /* private mode: the choice just lasts for this session */ }
  applyTheme();
}

// Event wiring for this panel, moved out of app.js's wireEvents().
export function initTheme() {
  $('#theme-button').addEventListener('click', cycleTheme);
  darkMediaQuery()?.addEventListener('change', () => {
    if (state.theme === 'system') applyTheme();
  });
}
