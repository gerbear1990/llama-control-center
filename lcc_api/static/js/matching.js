import { state } from './state.js';

export function profileMatches(profile) {
  const query = state.query.trim().toLowerCase();
  if (!query) return true;
  const haystack = [
    profile.mode,
    profile.name,
    profile.description,
    profile.model?.name,
    profile.model?.path,
  ].join(' ').toLowerCase();
  return haystack.includes(query);
}

export function modelMatches(model) {
  const query = state.query.trim().toLowerCase();
  if (!query) return true;
  return [model.name, model.path, model.quant, model.source].join(' ').toLowerCase().includes(query);
}

// Pure matcher: resolve a model file/dir path to its profile. Case- and
// slash-agnostic (Windows paths); prefers launchable exact matches when
// several profiles share one model file (e.g. an MTP variant).
export function profileForModelPath(profiles, path) {
  if (!path) return null;
  const norm = (p) => String(p || '').replace(/\//g, '\\').toLowerCase();
  const target = norm(path);
  const matches = (profiles || []).filter((p) => p.model && norm(p.model.path) === target);
  if (!matches.length) return null;
  const ranked = [...matches].sort((a, b) => (
    (b.launchable === true) - (a.launchable === true)
    || (b.confidence === 1.0) - (a.confidence === 1.0)
  ));
  return ranked[0];
}
