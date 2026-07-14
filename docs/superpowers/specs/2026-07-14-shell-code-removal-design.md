# Shell-Code Removal + Cleanup Pass — Design

**Date:** 2026-07-14
**Status:** Approved by user (conversation), pending spec review
**Scope decision:** "Scripts + portable CLI" removal, "Removal + cleanup + report" ambition.

## Goal

Remove everything in Llama Control Center that exists only to interact with a
shell outside the web UI, clean up repo hygiene, and deliver a prioritized
audit report of refactor / optimization / feature opportunities for later
passes. The web UI must lose no functionality: profile auto-registration,
exact profile→model matching, and server start/stop all keep working.

## What is being removed

1. **Launch-script generation** — `lcc_core/launch_scripts.py` rendering of
   `.ps1` / `.sh` files, the generated `scripts/*.ps1` artifacts, the
   `/api/launch-scripts` GET/POST endpoints in `lcc_api/app.py`, the
   `auto_generate_launch_scripts` config flag (`lcc_core/config.py`,
   `lcc_api/app.py` ConfigRequest), and its Settings checkbox in
   `index.html` / `app.js`. The startup autoscan hook
   (`startup_autoscan_if_enabled`) goes with it.
2. **Script parsing in `manifest.py`** — `_parse_model_path` reads the model
   path out of a generated `.ps1`; obsolete after the migration below.
3. **Portable CLI** — `lcc_core/cli.py`, `lcc_core/__main__.py`,
   `PORTABLE_CORE.md`, and README/dev-doc sections that reference
   `python -m lcc_core`.
4. **Tests for the above** — `tests/test_launch_scripts.py`,
   `tests/test_launch_smoke.py`, and CLI/script assertions inside
   `test_lcc_core.py` / `test_lcc_api.py`.

`scripts/capture_goal_evidence.py` (git-tracked, evidence tooling) stays.
Hand-written `scripts/stabilitymatrix*.ps1` files are untracked local files;
they are left on disk, untouched.

## What is being kept (and how)

- **Profile auto-registration.** `launch_scripts.py` is currently the module
  that registers newly discovered models as `models.json` profiles and
  repairs broken references. That logic moves to a new focused module,
  `lcc_core/profile_registry.py`, with the same registration behavior minus
  any file rendering. The API endpoint that triggered "scan" keeps working
  against the registry (renamed semantics: it registers profiles, no longer
  writes scripts).

## The migration (load-bearing step)

`manifest.py` resolves a profile's model path as
`entry.get("model_path") or _parse_model_path(script_path)`. Auto-generated
entries carry only `script`, so deleting scripts naively degrades matching to
fuzzy name matching.

**One-time migration:** for every `models.json` entry that lacks
`model_path`, resolve the path once (from the existing script file / current
resolver) and write it explicitly into the entry; drop the `script` field.
After migration, `manifest.py` reads `model_path` only.

Migration runs as a script during this pass (not shipped as ongoing code),
and the migrated `models.json` is committed.

## Sequencing

0. **Commit the in-flight vLLM-WSL/NVFP4 work first** (~900 uncommitted
   lines across 15 modified + 3 untracked paths: `lcc_core/vllm_args.py`,
   `docs/NVFP4_WSL.md`, `mcps/`) as its own commit, so the removal diff is
   clean. `graphify/`, `graphify-out/`, `terminals/` are NOT committed.
1. Migrate `models.json` (add `model_path`, drop `script`).
2. Extract `profile_registry.py`; delete `launch_scripts.py`, endpoints,
   config flag, Settings UI, generated `scripts/*.ps1`.
3. Simplify `manifest.py` (remove script parsing).
4. Delete portable CLI + `PORTABLE_CORE.md`; update README.
5. Delete/trim tests; keep suite green.
6. Repo hygiene: `.gitignore` additions (`terminals/`, `graphify/`,
   `graphify-out/`), remove stray smoke logs from the working tree.
7. Write the audit report.

## Error handling

- Migration: if an entry's model path cannot be resolved (missing script and
  no discovered model match), keep the entry, leave `model_path` absent, and
  list it in the migration output; the resolver already surfaces unresolved
  profiles as setup items rather than failing.
- Registry extraction preserves existing behavior for manifest read errors
  (`ManifestReadError` paths unchanged).

## Verification

- Full pytest suite green after each stage (baseline: 133 passed, 1 skipped).
- `node --check lcc_api/static/app.js`.
- Live check: start the app, confirm profiles resolve with exact matches
  (no new setup items vs. baseline), start and stop one tracked server from
  the UI.

## Deliverable: audit report

`docs/2026-07-14-audit.md`, prioritized, covering at minimum:

- **Refactors:** splitting `app.js` (3,821 lines) and `styles.css`
  (4,105 lines) into modules; `lcc_api/app.py` router extraction; large
  `lcc_core` modules (`server_manager.py` 1,128, `estimates.py` 998,
  `hardware.py` 994).
- **Optimizations** found during the audit.
- **Feature wins** cross-referenced against ROADMAP.md — cheapest
  high-value items are the shipped-backend/missing-UI trio: crash-watchdog
  UI, live server metrics panel, log tail panel; plus quant picker.

The report recommends; it does not implement. Larger refactors are executed
in later passes.
