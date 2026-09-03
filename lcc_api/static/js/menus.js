// Two menu systems: the Parameters tools disclosure, and one shared
import { $, $$ } from './util.js';

// popup <ul> reused across the dashboard.

// ----- Tools disclosure (Parameters panel) ----------------------------------
// Start / Stop / Show command / Save parameters stay on the surface; the six
// occasional tools fold into this menu. The buttons themselves move inside it
// rather than being re-created, so every existing handler and id keeps working.
export let toolsMenuKeyHandler = null;

export let toolsMenuOutsideHandler = null;

export function toolsMenuItems() {
  return $$('#tools-menu .mini-button').filter((button) => !button.disabled);
}

export function closeToolsMenu({ restoreFocus = false } = {}) {
  const menu = $('#tools-menu');
  const trigger = $('#tools-menu-button');
  if (!menu || menu.hidden) return;
  menu.hidden = true;
  trigger?.setAttribute('aria-expanded', 'false');
  document.removeEventListener('mousedown', toolsMenuOutsideHandler, true);
  document.removeEventListener('keydown', toolsMenuKeyHandler, true);
  toolsMenuOutsideHandler = null;
  toolsMenuKeyHandler = null;
  if (restoreFocus) trigger?.focus();
}

export function openToolsMenu() {
  const menu = $('#tools-menu');
  const trigger = $('#tools-menu-button');
  if (!menu || !trigger) return;
  menu.hidden = false;
  trigger.setAttribute('aria-expanded', 'true');
  toolsMenuItems()[0]?.focus();

  toolsMenuOutsideHandler = (event) => {
    if (menu.contains(event.target) || trigger.contains(event.target)) return;
    closeToolsMenu();
  };
  toolsMenuKeyHandler = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeToolsMenu({ restoreFocus: true });
      return;
    }
    if (event.key === 'Tab') {
      closeToolsMenu();
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    const items = toolsMenuItems();
    if (!items.length) return;
    const step = event.key === 'ArrowDown' ? 1 : -1;
    const current = items.indexOf(document.activeElement);
    const next = (current + step + items.length) % items.length;
    items[next].focus();
  };
  // Capture, so the menu closes before any handler bound to the trigger row.
  setTimeout(() => {
    document.addEventListener('mousedown', toolsMenuOutsideHandler, true);
    document.addEventListener('keydown', toolsMenuKeyHandler, true);
  }, 0);
}

export function wireToolsMenu() {
  const menu = $('#tools-menu');
  const trigger = $('#tools-menu-button');
  if (!menu || !trigger) return;
  menu.querySelectorAll('.mini-button').forEach((button) => button.setAttribute('role', 'menuitem'));
  trigger.addEventListener('click', () => {
    if (menu.hidden) openToolsMenu();
    else closeToolsMenu({ restoreFocus: true });
  });
  // Capture phase: focus is back on the trigger before the tool's own handler
  // runs, so a modal it opens returns focus somewhere still visible.
  menu.addEventListener('click', (event) => {
    if (!event.target.closest('.mini-button')) return;
    closeToolsMenu({ restoreFocus: true });
  }, true);
}

// ----- Popup menu component -------------------------------------------------
// One shared <ul> element reused across the dashboard. Anchors to a trigger
// element, positions itself below it, closes on outside click / Escape, and
// supports keyboard arrow nav. Items: { id?, label, danger?, disabled?, onSelect }.
export let popupMenuEl = null;

export let popupMenuItems = [];

export let popupMenuActiveIndex = 0;

export let popupMenuOutsideHandler = null;

export let popupMenuKeyHandler = null;

export let popupMenuTrigger = null;

export function closePopupMenu() {
  if (popupMenuEl) {
    popupMenuEl.remove();
    popupMenuEl = null;
  }
  // The trigger advertises the menu with aria-haspopup; its aria-expanded has
  // to come back down or assistive tech keeps reporting an open menu.
  popupMenuTrigger?.setAttribute('aria-expanded', 'false');
  popupMenuTrigger = null;
  popupMenuItems = [];
  document.removeEventListener('mousedown', popupMenuOutsideHandler, true);
  document.removeEventListener('keydown', popupMenuKeyHandler, true);
  popupMenuOutsideHandler = null;
  popupMenuKeyHandler = null;
}

export function showPopupMenu(trigger, items) {
  closePopupMenu();
  if (!Array.isArray(items) || items.length === 0) return;
  popupMenuItems = items.filter((item) => !item.hidden);
  popupMenuTrigger = trigger;
  trigger?.setAttribute('aria-haspopup', 'menu');
  trigger?.setAttribute('aria-expanded', 'true');

  const menu = document.createElement('ul');
  menu.className = 'popup-menu';
  menu.setAttribute('role', 'menu');
  popupMenuItems.forEach((item, index) => {
    if (item.separator) {
      const sep = document.createElement('li');
      sep.className = 'popup-menu-separator';
      sep.setAttribute('role', 'separator');
      menu.appendChild(sep);
      return;
    }
    const li = document.createElement('li');
    li.setAttribute('role', 'menuitem');
    li.className = `popup-menu-item${item.danger ? ' danger' : ''}${item.disabled ? ' disabled' : ''}`;
    li.tabIndex = -1;
    li.textContent = item.label;
    li.title = item.title || '';
    li.dataset.index = String(index);
    if (!item.disabled) {
      li.addEventListener('click', (event) => {
        event.stopPropagation();
        closePopupMenu();
        try { item.onSelect?.(); } catch (err) { console.error(err); }
      });
    }
    menu.appendChild(li);
  });
  document.body.appendChild(menu);
  popupMenuEl = menu;

  // Position below the trigger, flipping above if it would overflow viewport.
  const rect = trigger.getBoundingClientRect();
  menu.style.visibility = 'hidden';
  requestAnimationFrame(() => {
    const menuRect = menu.getBoundingClientRect();
    const fitsBelow = rect.bottom + menuRect.height + 8 <= window.innerHeight;
    const top = fitsBelow
      ? rect.bottom + window.scrollY + 4
      : rect.top + window.scrollY - menuRect.height - 4;
    const left = Math.min(
      rect.left + window.scrollX,
      window.scrollX + window.innerWidth - menuRect.width - 8,
    );
    menu.style.top = `${Math.max(top, window.scrollY + 4)}px`;
    menu.style.left = `${Math.max(left, window.scrollX + 4)}px`;
    menu.style.visibility = 'visible';
    popupMenuActiveIndex = 0;
    const first = menu.querySelector('.popup-menu-item:not(.disabled)');
    first?.classList.add('active');
    first?.focus();
  });

  popupMenuOutsideHandler = (event) => {
    if (!popupMenuEl) return;
    if (popupMenuEl.contains(event.target) || trigger.contains(event.target)) return;
    closePopupMenu();
  };
  popupMenuKeyHandler = (event) => {
    if (!popupMenuEl) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      closePopupMenu();
      trigger.focus();
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      // Skip separators; only enabled non-separator items are focusable.
      const enabled = popupMenuItems
        .map((item, idx) => ({ item, idx }))
        .filter(({ item }) => !item.disabled && !item.separator);
      if (enabled.length === 0) return;
      const pos = enabled.findIndex(({ idx }) => idx === popupMenuActiveIndex);
      const next = enabled[(pos + step + enabled.length) % enabled.length];
      popupMenuActiveIndex = next.idx;
      menu.querySelectorAll('.popup-menu-item').forEach((el, idx) => {
        el.classList.toggle('active', idx === popupMenuActiveIndex);
      });
      menu.querySelector(`.popup-menu-item[data-index="${popupMenuActiveIndex}"]`)?.focus();
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      const current = popupMenuItems[popupMenuActiveIndex];
      if (current && !current.disabled) {
        closePopupMenu();
        try { current.onSelect?.(); } catch (err) { console.error(err); }
      }
    }
  };
  // Use capture so the outside-click fires before any handler bound to the
  // trigger element (e.g. our row-click listener).
  setTimeout(() => {
    document.addEventListener('mousedown', popupMenuOutsideHandler, true);
    document.addEventListener('keydown', popupMenuKeyHandler, true);
  }, 0);
}
