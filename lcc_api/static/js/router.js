// Destinations, session views, panel routing and collapse state.

import { consoleSummaryLine } from './panels/profiles.js';
import { loadLogs } from './panels/logs.js';
import { pollLiveHardware } from './panels/hardware.js';
import { $, $$ } from './util.js';
import { state } from './state.js';

export const PANEL_COLLAPSE_KEY = 'lcc-collapsed-panels';

export const DEFAULT_COLLAPSED_PANELS = [];

export const DESTINATIONS = {
  console: { title: 'Console', summary: 'Selected profile, memory fit, and Start.' },
  inventory: { title: 'Inventory', summary: 'Runtimes, profiles, and local models.' },
  tools: { title: 'Tools', summary: 'Hugging Face, portability, and Settings.' },
};

export const SESSION_VIEWS = ['stage', 'chat', 'logs', 'server'];

export const PANEL_ROUTE = {
  console: { dest: 'console', session: 'stage' },
  stage: { dest: 'console', session: 'stage' },
  parameters: { dest: 'console', session: 'stage' },
  chat: { dest: 'console', session: 'chat' },
  logs: { dest: 'console', session: 'logs' },
  servers: { dest: 'console', session: 'server' },
  server: { dest: 'console', session: 'server' },
  inventory: { dest: 'inventory' },
  runtimes: { dest: 'inventory' },
  profiles: { dest: 'inventory' },
  models: { dest: 'inventory' },
  tools: { dest: 'tools' },
  'hf-tools': { dest: 'tools' },
  portability: { dest: 'tools' },
};

export function loadCollapsedPanels() {
  try {
    const raw = JSON.parse(localStorage.getItem(PANEL_COLLAPSE_KEY));
    if (Array.isArray(raw)) return new Set(raw);
  } catch (error) {
    /* fall through to defaults */
  }
  return new Set(DEFAULT_COLLAPSED_PANELS);
}

export function showDestination(dest, session) {
  const nextDest = DESTINATIONS[dest] ? dest : 'console';
  const nextSession = SESSION_VIEWS.includes(session) ? session : 'stage';
  const main = $('.main');
  if (main) {
    main.dataset.destination = nextDest;
    main.dataset.session = nextSession;
  }
  $$('.destination').forEach((el) => {
    el.hidden = el.dataset.destination !== nextDest;
  });
  $$('.nav-item[data-destination]').forEach((el) => {
    const on = el.dataset.destination === nextDest;
    el.classList.toggle('active', on);
    if (on) el.setAttribute('aria-current', 'page');
    else el.removeAttribute('aria-current');
  });
  $$('.session-tab').forEach((el) => {
    const on = el.dataset.session === nextSession;
    el.classList.toggle('active', on);
    el.setAttribute('aria-selected', String(on));
  });
  $$('.session-view').forEach((el) => {
    el.hidden = el.dataset.session !== nextSession;
  });
  const heading = $('#topbar-heading');
  if (heading) heading.textContent = DESTINATIONS[nextDest].title;
  const summary = $('#summary-line');
  if (summary) {
    if (nextDest === 'console') {
      summary.textContent = consoleSummaryLine();
    } else {
      summary.textContent = DESTINATIONS[nextDest].summary;
    }
  }
  try {
    localStorage.setItem('lcc-destination', nextDest);
    localStorage.setItem('lcc-session', nextSession);
  } catch { /* private mode */ }
  const hash = nextDest === 'console' && nextSession !== 'stage'
    ? (nextSession === 'server' ? 'servers' : nextSession)
    : nextDest;
  if (location.hash !== `#${hash}`) {
    history.replaceState(null, '', `#${hash}`);
  }
  if (nextSession === 'logs' && state.selectedServerId) {
    loadLogs(state.selectedServerId, null, { silent: true });
  }
}

export function showPanel(id) {
  const mapped = PANEL_ROUTE[id] || PANEL_ROUTE.console;
  showDestination(mapped.dest, mapped.session);
}

export function applyHashRoute() {
  const id = (location.hash || '').replace(/^#/, '');
  if (id && PANEL_ROUTE[id]) {
    showPanel(id);
    return;
  }
  let dest = 'console';
  let session = 'stage';
  try {
    dest = localStorage.getItem('lcc-destination') || dest;
    session = localStorage.getItem('lcc-session') || session;
  } catch { /* ignore */ }
  showDestination(dest, session);
}

// Open the destination that owns this panel, then uncollapse it if it still
// uses the inventory accordion.
export function revealPanel(id) {
  showPanel(id);
  const panel = document.getElementById(id);
  if (!panel) return;
  panel.classList.remove('collapsed');
  const toggle = panel.querySelector('.panel-toggle');
  if (toggle) toggle.setAttribute('aria-expanded', 'true');
  try {
    const raw = JSON.parse(localStorage.getItem(PANEL_COLLAPSE_KEY));
    const next = new Set(Array.isArray(raw) ? raw : DEFAULT_COLLAPSED_PANELS);
    next.delete(id);
    localStorage.setItem(PANEL_COLLAPSE_KEY, JSON.stringify([...next]));
  } catch { /* ignore persist failures; the panel is already open */ }
}

export function enhancePanels() {
  const collapsed = loadCollapsedPanels();
  const saveState = () => localStorage.setItem(PANEL_COLLAPSE_KEY, JSON.stringify([...collapsed]));

  $$('.panel').forEach((panel) => {
    if (panel.closest('.session-view, #destination-tools')) return;
    const heading = panel.querySelector(':scope > .panel-heading');
    if (!heading || panel.querySelector(':scope > .panel-body')) return;

    const inner = document.createElement('div');
    inner.className = 'panel-body-inner';
    let node = heading.nextSibling;
    while (node) {
      const next = node.nextSibling;
      inner.appendChild(node);
      node = next;
    }
    const body = document.createElement('div');
    body.className = 'panel-body';
    body.appendChild(inner);
    panel.appendChild(body);

    const id = panel.id;
    const titleZone = heading.querySelector(':scope > div');
    const headingName = heading.querySelector('h3')?.textContent.trim() || 'section';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'panel-toggle';
    toggle.innerHTML = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    heading.appendChild(toggle);

    const apply = (isCollapsed, persist) => {
      panel.classList.toggle('collapsed', isCollapsed);
      toggle.setAttribute('aria-expanded', String(!isCollapsed));
      toggle.setAttribute('aria-label', `${isCollapsed ? 'Expand' : 'Collapse'} ${headingName}`);
      if (persist) {
        if (isCollapsed) collapsed.add(id);
        else collapsed.delete(id);
        saveState();
      }
    };
    apply(collapsed.has(id), false);

    const flip = () => apply(!panel.classList.contains('collapsed'), true);
    toggle.addEventListener('click', (event) => { event.stopPropagation(); flip(); });
    if (titleZone) {
      titleZone.classList.add('panel-title-toggle');
      titleZone.addEventListener('click', flip);
    }
  });
}

export function enhanceSidebar() {
  const shell = $('.app-shell');
  const collapsed = localStorage.getItem('lcc-sidebar-collapsed') === '1';
  shell.classList.toggle('sidebar-collapsed', collapsed);
  $$('.nav-item').forEach((item) => {
    const label = item.querySelector('span:last-child');
    if (label && !item.title) item.title = label.textContent.trim();
  });
  const toggle = $('#sidebar-toggle');
  const setToggleLabel = (collapsed) => {
    if (!toggle) return;
    toggle.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    toggle.setAttribute('title', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    toggle.setAttribute('aria-expanded', String(!collapsed));
  };
  setToggleLabel(collapsed);
  toggle.addEventListener('click', () => {
    const next = !shell.classList.contains('sidebar-collapsed');
    shell.classList.toggle('sidebar-collapsed', next);
    localStorage.setItem('lcc-sidebar-collapsed', next ? '1' : '0');
    setToggleLabel(next);
    // Expanding reveals a widget that was sampling but not painting: draw the
    // recorded history immediately instead of waiting out the poll interval.
    if (!next) pollLiveHardware();
  });
}

export function syncSearchInputs(value) {
  const input = $('#search-input');
  if (input && input.value !== value) input.value = value;
}

export function persistDisclosure(el, key) {
  if (!el) return;
  try {
    if (localStorage.getItem(key) === '1') el.open = true;
  } catch { /* private mode */ }
  el.addEventListener('toggle', () => {
    try {
      localStorage.setItem(key, el.open ? '1' : '0');
    } catch { /* private mode */ }
  });
}
