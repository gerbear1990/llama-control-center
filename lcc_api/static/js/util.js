// Leaf utilities: no DOM at module scope, no imports, no app knowledge.

export const $ = (selector) => document.querySelector(selector);

export const $$ = (selector) => Array.from(document.querySelectorAll(selector));

export const hasOwn = (object, key) => Object.prototype.hasOwnProperty.call(object || {}, key);

export function formatBytes(bytes) {
  if (!bytes) return '-';
  const gb = bytes / 1024 ** 3;
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  const mb = bytes / 1024 ** 2;
  return `${mb.toFixed(0)} MB`;
}

export function formatMib(mib) {
  if (mib === undefined || mib === null || Number.isNaN(Number(mib))) return '-';
  const value = Number(mib);
  if (Math.abs(value) >= 1024) return `${(value / 1024).toFixed(1)} GB`;
  return `${Math.round(value)} MiB`;
}

export function formatNumber(value, digits = 2) {
  if (value === undefined || value === null || value === '') return '-';
  if (typeof value === 'boolean') return value ? 'on' : 'off';
  if (typeof value !== 'number') return String(value);
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(digits)));
}

export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

export function listToLines(values) {
  return (values || []).filter(Boolean).join('\n');
}

export function linesToList(value) {
  return String(value || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

export function dirname(path) {
  const idx = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
  return idx > 0 ? path.slice(0, idx) : '';
}
