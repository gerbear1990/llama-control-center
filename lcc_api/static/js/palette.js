// Command palette. The command bodies live in app.js and arrive via
import { $, escapeHtml } from './util.js';

// registerCommands() -- importing panels here would be a cycle.

export let paletteVisible = false;

export let paletteReturnFocus = null;

// Static by design: the palette list is a pure value, so it stays testable
// outside the DOM. Availability is decided when a command runs, not here.
export function getCommands() {
  return [
    { id: 'focus-search', label: 'Focus search', shortcut: 'Ctrl+K' },
    { id: 'start-profile', label: 'Start selected profile' },
    { id: 'stop-profile', label: 'Stop selected profile' },
    { id: 'restart-profile', label: 'Restart selected profile' },
    { id: 'smart-fit', label: 'Smart fit selected profile' },
    { id: 'fit-test', label: 'Run fit test' },
    { id: 'benchmark', label: 'Run benchmark' },
    { id: 'open-logs', label: 'Open logs' },
    { id: 'purge-stopped', label: 'Purge stopped servers' },
    { id: 'new-profile', label: 'New profile…' },
    { id: 'save-profile-copy', label: 'Save profile as copy…' },
    { id: 'toggle-theme', label: 'Cycle theme (light / dark / system)' },
    { id: 'open-settings', label: 'Open Settings' },
    { id: 'refresh', label: 'Refresh inventory' },
  ];
}

// The command bodies close over panel state, so they are registered from
// app.js rather than imported here -- palette importing panels would be a
// cycle, and the palette does not need to know what a command does.
let registry = {};

export function registerCommands(commands) {
  registry = commands || {};
}

export function executeCommand(id) {
  const fn = registry[id];
  if (typeof fn === 'function') {
    fn();
    return true;
  }
  return false;
}

export function showCommandPalette() {
  const back = $('#command-palette');
  if (!back) return;
  paletteReturnFocus = document.activeElement;
  back.hidden = false;
  document.body.classList.add('modal-open');
  paletteVisible = true;
  renderPaletteList('');
  const filter = $('#palette-filter');
  if (filter) {
    filter.value = '';
    filter.focus();
    filter.oninput = () => renderPaletteList(filter.value);
    // Basic keyboard nav for palette list (up/down/enter)
    filter.onkeydown = (ev) => {
      const items = Array.from($('#palette-list').querySelectorAll('li[data-cmd]'));
      if (!items.length) return;
      let sel = items.findIndex(i => i.classList.contains('selected'));
      if (sel < 0) sel = 0;
      if (ev.key === 'ArrowDown') {
        ev.preventDefault();
        sel = (sel + 1) % items.length;
        setPaletteSelection(items, sel);
      } else if (ev.key === 'ArrowUp') {
        ev.preventDefault();
        sel = (sel - 1 + items.length) % items.length;
        setPaletteSelection(items, sel);
      } else if (ev.key === 'Enter') {
        ev.preventDefault();
        const chosen = items[sel >=0 ? sel : 0];
        if (chosen) {
          const id = chosen.dataset.cmd;
          hideCommandPalette();
          executeCommand(id);
        }
      }
    };
  }
}

export function hideCommandPalette() {
  const back = $('#command-palette');
  if (back) back.hidden = true;
  document.body.classList.remove('modal-open');
  paletteVisible = false;
  // Hand the keyboard back to whatever had it before the palette opened.
  // A command that moves focus itself (Focus search) runs after this and wins.
  if (paletteReturnFocus && typeof paletteReturnFocus.focus === 'function') {
    paletteReturnFocus.focus({ preventScroll: true });
  }
  paletteReturnFocus = null;
}

// Focus stays in the filter box, so the highlighted row is announced through
// aria-activedescendant rather than by moving focus into the list.
export function setPaletteSelection(items, index) {
  items.forEach((item, idx) => {
    const active = idx === index;
    item.classList.toggle('selected', active);
    item.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  const current = items[index];
  if (!current) return;
  current.scrollIntoView({ block: 'nearest' });
  $('#palette-filter')?.setAttribute('aria-activedescendant', current.id);
}

export function renderPaletteList(filterText) {
  const list = $('#palette-list');
  if (!list) return;
  const q = (filterText || '').toLowerCase().trim();
  const cmds = getCommands().filter(c => !q || c.label.toLowerCase().includes(q) || c.id.includes(q));
  list.innerHTML = cmds.map((c) => `
    <li id="palette-option-${escapeHtml(c.id)}" role="option" aria-selected="false" data-cmd="${escapeHtml(c.id)}">
      <span>${escapeHtml(c.label)}</span>
      ${c.shortcut ? `<kbd>${escapeHtml(c.shortcut)}</kbd>` : ''}
    </li>
  `).join('') || '<li class="empty" role="presentation">No matching commands</li>';
  // click to execute
  const items = Array.from(list.querySelectorAll('li[data-cmd]'));
  items.forEach(li => {
    li.addEventListener('click', () => {
      const id = li.dataset.cmd;
      hideCommandPalette();
      executeCommand(id);
    });
  });
  if (items.length) setPaletteSelection(items, 0);
  else $('#palette-filter')?.removeAttribute('aria-activedescendant');
}

// Event wiring for this panel, moved out of app.js's wireEvents().
export function initPalette() {
  // Backdrop close: a click on the palette's own backdrop dismisses it.
  const palBack = $('#command-palette');
  if (palBack) palBack.addEventListener('click', (e) => { if (e.target.id === 'command-palette') hideCommandPalette(); });
}
