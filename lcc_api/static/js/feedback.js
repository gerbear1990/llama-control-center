// Toasts, busy states, confirm dialogs and tooltips -- the app's
import { $, $$ } from './util.js';

// out-of-band conversation with the operator.

// Toasts are short text snippets shown in the bottom-right. They may carry
// a single optional action button (e.g. 'Use port 18100') that the user can
// click while the toast is still visible. ``toast.action(message, action)`` is
// the recommended form; ``toast(message)`` keeps the simple text-only path
// so existing call sites are unchanged.
export function toast(message, action) {
  const el = $('#toast');
  el.innerHTML = '';
  const text = document.createElement('span');
  text.textContent = message;
  el.appendChild(text);
  const persist = Boolean(action && action.label && typeof action.onClick === 'function');
  if (persist) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'toast-action';
    button.textContent = action.label;
    button.addEventListener('click', () => {
      window.clearTimeout(toast.timer);
      el.classList.remove('show');
      action.onClick();
    });
    el.appendChild(button);
    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'toast-action';
    dismiss.setAttribute('aria-label', 'Dismiss');
    dismiss.textContent = 'Dismiss';
    dismiss.addEventListener('click', () => {
      window.clearTimeout(toast.timer);
      el.classList.remove('show');
    });
    el.appendChild(dismiss);
  }
  el.classList.add('show');
  window.clearTimeout(toast.timer);
  toast.timer = persist ? null : window.setTimeout(() => el.classList.remove('show'), 5000);
}

// The busy state hides the label behind a spinner, so the visual change has to
// be mirrored with aria-busy — otherwise a screen reader still reads the button
// as idle while the request is in flight.
export async function withBusy(button, fn) {
  if (!button) return fn();
  const wasDisabled = button.disabled;
  button.disabled = true;
  button.classList.add('busy');
  button.setAttribute('aria-busy', 'true');
  try {
    return await fn();
  } finally {
    button.disabled = wasDisabled;
    button.classList.remove('busy');
    button.removeAttribute('aria-busy');
  }
}

export function setActionsBusy(mode, busy) {
  $$(`button[data-mode="${CSS.escape(mode || '')}"]`).forEach((button) => {
    if (busy) {
      button.disabled = true;
      button.classList.add('busy');
      button.setAttribute('aria-busy', 'true');
    } else {
      button.disabled = false;
      button.classList.remove('busy');
      button.removeAttribute('aria-busy');
    }
  });
}

export function confirmAction({ title = 'Confirm', message = '', confirmLabel = 'Confirm', cancelLabel = 'Cancel', confirmKind = 'primary' } = {}) {
  const modal = $('#confirm-modal');
  const titleEl = $('#confirm-title');
  const messageEl = $('#confirm-message');
  const okButton = $('#confirm-ok');
  const cancelButton = $('#confirm-cancel');
  titleEl.textContent = title;
  messageEl.textContent = message;
  okButton.textContent = confirmLabel;
  cancelButton.textContent = cancelLabel;
  okButton.classList.remove('primary', 'danger');
  if (confirmKind === 'danger') okButton.classList.add('danger');
  else okButton.classList.add('primary');
  modal.hidden = false;
  okButton.disabled = false;
  cancelButton.disabled = false;
  document.body.classList.add('modal-open');
  const priorFocus = document.activeElement;
  // A destructive action has to be aimed at: land on Cancel so a stray Enter
  // dismisses instead of deleting. Safe confirms still open on OK.
  const isDanger = confirmKind === 'danger';
  (isDanger ? cancelButton : okButton).focus();
  return new Promise((resolve) => {
    function cleanup() {
      modal.hidden = true;
      document.body.classList.remove('modal-open');
      okButton.removeEventListener('click', onOk);
      cancelButton.removeEventListener('click', onCancel);
      modal.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      if (priorFocus && typeof priorFocus.focus === 'function') {
        priorFocus.focus();
      }
    }
    function onOk() { cleanup(); resolve(true); }
    function onCancel() { cleanup(); resolve(false); }
    function onBackdrop(event) { if (event.target === modal) onCancel(); }
    function onKey(event) {
      if (event.key === 'Escape') {
        onCancel();
      } else if (event.key === 'Enter') {
        // Enter fires the button that actually has focus. No blanket-OK:
        // confirming a delete must be a deliberate landing on Delete.
        const active = document.activeElement;
        if (active === cancelButton) {
          event.preventDefault();
          onCancel();
        } else if (active === okButton) {
          event.preventDefault();
          onOk();
        }
      } else {
        trapTab(event, $('.confirm-dialog'));
      }
    }
    okButton.addEventListener('click', onOk);
    cancelButton.addEventListener('click', onCancel);
    modal.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);
  });
}

// Drives the name/description modal shared by "Save profile" and the row
// menu's "Save as copy". Resolves with {name, description} on OK and null on
// Cancel / Escape / backdrop click. Every listener is transient and removed in
// cleanup(), and focus returns to whatever opened the modal.
export function promptProfileDetails({ title = 'Save parameters', okLabel = 'Save', name = '', description = '', message = '' } = {}) {
  const modal = $('#save-profile-modal');
  const titleEl = $('#save-profile-title');
  const noteEl = $('#save-profile-note');
  const nameInput = $('#save-profile-name');
  const descInput = $('#save-profile-desc');
  const okButton = $('#save-profile-ok');
  const cancelButton = $('#save-profile-cancel');
  if (!modal || !nameInput || !descInput || !okButton || !cancelButton) return Promise.resolve(null);
  if (titleEl) titleEl.textContent = title;
  if (noteEl) {
    noteEl.textContent = message;
    noteEl.hidden = !message;
  }
  okButton.textContent = okLabel;
  nameInput.value = name;
  descInput.value = description;
  modal.hidden = false;
  document.body.classList.add('modal-open');
  const priorFocus = document.activeElement;
  nameInput.focus();
  nameInput.select();
  return new Promise((resolve) => {
    function cleanup() {
      modal.hidden = true;
      document.body.classList.remove('modal-open');
      okButton.removeEventListener('click', onOk);
      cancelButton.removeEventListener('click', onCancel);
      modal.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      if (priorFocus && typeof priorFocus.focus === 'function') {
        priorFocus.focus();
      }
    }
    function onOk() {
      const value = nameInput.value.trim();
      // An empty name would save an unlabelled profile; keep the modal open.
      if (!value) {
        nameInput.focus();
        return;
      }
      cleanup();
      resolve({ name: value, description: descInput.value.trim() });
    }
    function onCancel() { cleanup(); resolve(null); }
    function onBackdrop(event) { if (event.target === modal) onCancel(); }
    function onKey(event) {
      if (event.key === 'Escape') onCancel();
      else if (event.key === 'Enter') { event.preventDefault(); onOk(); }
      else trapTab(event, modal.querySelector('.rename-dialog'));
    }
    okButton.addEventListener('click', onOk);
    cancelButton.addEventListener('click', onCancel);
    modal.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);
  });
}

export function floatingTooltip() {
  let el = $('#floating-tooltip');
  if (!el) {
    el = document.createElement('div');
    el.id = 'floating-tooltip';
    el.className = 'floating-tooltip';
    el.hidden = true;
    document.body.appendChild(el);
  }
  return el;
}

export function showFloatingTooltip(trigger) {
  const text = trigger.dataset.tooltip;
  if (!text) return;
  const tooltip = floatingTooltip();
  tooltip.textContent = text;
  tooltip.hidden = false;
  tooltip.classList.remove('visible');
  tooltip.style.left = '0px';
  tooltip.style.top = '-9999px';

  window.requestAnimationFrame(() => {
    const triggerRect = trigger.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const margin = 12;
    let left = triggerRect.left + (triggerRect.width / 2) - (tooltipRect.width / 2);
    left = Math.max(margin, Math.min(left, window.innerWidth - tooltipRect.width - margin));

    let top = triggerRect.top - tooltipRect.height - 9;
    if (top < margin) {
      top = triggerRect.bottom + 9;
    }
    top = Math.max(margin, Math.min(top, window.innerHeight - tooltipRect.height - margin));

    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
    tooltip.classList.add('visible');
  });
}

export function hideFloatingTooltip() {
  const tooltip = $('#floating-tooltip');
  if (!tooltip) return;
  tooltip.classList.remove('visible');
  window.clearTimeout(hideFloatingTooltip.timer);
  hideFloatingTooltip.timer = window.setTimeout(() => {
    tooltip.hidden = true;
  }, 130);
}

export function bindHelpDot(help) {
  if (help.dataset.tooltipBound === 'true') return;
  help.dataset.tooltipBound = 'true';
  help.addEventListener('mouseenter', () => showFloatingTooltip(help));
  help.addEventListener('focus', () => showFloatingTooltip(help));
  help.addEventListener('mousedown', (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  help.addEventListener('click', (event) => {
    event.preventDefault();
    event.stopPropagation();
    help.focus({ preventScroll: true });
    showFloatingTooltip(help);
  });
  help.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    event.stopPropagation();
    showFloatingTooltip(help);
  });
  help.addEventListener('mouseleave', hideFloatingTooltip);
  help.addEventListener('blur', hideFloatingTooltip);
}

export function enhanceTooltips() {
  $$([
    '#param-form .field[title]',
    '#param-form .check-row label[title]',
    '#param-form .estimate-card[title]',
    '#settings-form .field[title]',
  ].join(',')).forEach((el) => {
    const text = el.getAttribute('title');
    if (!text || el.dataset.tooltipEnhanced === 'true') return;
    el.dataset.tooltipEnhanced = 'true';
    el.removeAttribute('title');
    const target = (el.classList.contains('field') || el.classList.contains('estimate-card'))
      ? el.querySelector('span')
      : el;
    if (!target) return;
    const help = document.createElement('span');
    help.className = 'help-dot';
    help.dataset.tooltip = text;
    help.tabIndex = 0;
    help.setAttribute('role', 'button');
    help.setAttribute('aria-label', text);
    help.innerHTML = '<svg viewBox="0 0 16 16" width="10" height="10" aria-hidden="true" focusable="false"><circle cx="8" cy="3.6" r="1.6" fill="currentColor"/><rect x="6.6" y="6.2" width="2.8" height="6.8" rx="0.6" fill="currentColor"/></svg>';
    target.appendChild(help);
    bindHelpDot(help);
  });
}

// Generic focus helpers for modal dialogs. They live here rather than in
// settings.js because confirmAction and promptProfileDetails need them too,
// and settings importing feedback while feedback imports settings is a cycle.
export function focusableInside(container) {
  if (!container) return [];
  const selector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  return Array.from(container.querySelectorAll(selector))
    .filter((el) => el.offsetParent !== null || el === document.activeElement);
}

// Shared Tab trap for every modal dialog in the app: while the backdrop is up,
// Tab and Shift+Tab cycle inside ``dialog`` instead of walking into the page
// behind it. Call from a dialog's own keydown handler; non-Tab keys pass through.
export function trapTab(event, dialog) {
  if (event.key !== 'Tab' || !dialog) return;
  const items = focusableInside(dialog);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  const active = document.activeElement;
  if (event.shiftKey) {
    if (active === first || !dialog.contains(active)) {
      event.preventDefault();
      last.focus();
    }
  } else if (active === last || !dialog.contains(active)) {
    event.preventDefault();
    first.focus();
  }
}
