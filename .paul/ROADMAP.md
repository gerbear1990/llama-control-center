---
description: "Llama Control Center — milestone and phase structure"
type: Roadmap
about: "llama-control-center"
---

# Roadmap: Llama Control Center

## Overview

v0.16.0 shipped the shell-code removal and the ground-truth memory layer. v0.17.0 closes
the loop that's currently half-open: finish the in-flight UI restyle, make embedded-MTP
models usable end-to-end, extend fit/auto-tune to vLLM-WSL, then surface the three
observability backends that already exist but have no UI. The frontend split lands last
in the milestone because it must not collide with the restyle.

## Current Milestone

**v0.17.0 — Close the Open Loops**
Status: In progress
Phases: 1 of 6 complete

## Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 1 | Terminal-Instrument Design Pass | 1 | ✅ Complete | 2026-08-21 |
| 2 | Embedded-MTP Support | 1 | 🚧 Planning | - |
| 3 | vLLM-WSL Fit Estimator + Auto-Tuner | TBD | Not started | - |
| 4 | Running-Server Observability UI | TBD | Not started | - |
| 5 | Frontend Module Split | TBD | Not started | - |
| 6 | Release v0.17.0 | TBD | Not started | - |

## Phase Details

### Phase 1: Terminal-Instrument Design Pass

**Goal:** Machine data reads in monospace, structure drawn with 1px hairlines instead of
shadows/lifts, active pane carries an accent left edge — with zero colour changes.
**Status:** ✅ Complete 2026-08-21 — landed as `820e873` (UI) and `cb1818f` (backend half
of the same working session), plus `ad85599` retiring TODO.md.
**Note:** the plan document's 32 step checkboxes were never ticked during execution, so
plan-state there is not a reliable completion signal — the commits are.

**Source:** `docs/superpowers/plans/2026-07-17-terminal-instrument-design.md` + matching spec

---

### Phase 2: Embedded-MTP Support

**Goal:** Close issue #14. Discovery landed in `cb1818f`; this phase makes embedded-MTP
profiles *launchable* and adds the regression cover that fix never got.
**Plan:** `.paul/phases/02-embedded-mtp/02-01-PLAN.md`
**Depends on:** Nothing
**Research:** Unlikely (root cause already traced)

**Scope:**
- T7 — MTP detection: bump gguf-meta cache to v4, grow meta tuple to 5 elements
  (n_layer, kv_dims, supports_tools, context_length, mtp), scan `reader.tensors` for
  nextn/mtp names, `_store_meta_cache(..., mtp=)`, add `model_has_builtin_mtp`
- T8 — resolver: stop demanding `draft_model` for built-in MTP (`profile_resolver.py:180`)
- **Registry fix (not in the original plan) — ✅ already done in the uncommitted WIP.**
  `DRAFT_NAME_RE` in `profile_registry.py` has been replaced by `_is_draft_model()`, which no
  longer skips a model just because "MTP" appears mid-name. ⚠️ It exists **only in the working
  tree** — HEAD still carries the old regex, so land that WIP or the bug returns. Add a
  regression test pinning `NVFP4-MTP-Q8attn`-style names as *not* companions.
- `--spec-type draft-mtp` as a profile param so MTP weights aren't loaded as dead capacity
  (`fit.py:build_fit_args`)

**Source:** `docs/superpowers/plans/2026-07-14-models-pane-and-fixes.md` (T7–T8) + issue #14

---

### Phase 3: vLLM-WSL Fit Estimator + Auto-Tuner

**Goal:** vLLM-in-WSL profiles get the same fit estimate and auto-tune treatment as llama.cpp.
**Depends on:** Phase 2 (shares the estimator/resolver surface)
**Research:** Likely (vLLM memory model differs from llama.cpp's)

**Scope:**
- T9–T10 — vLLM estimator + tuner
- T11 — calibration against real benchmarks

**Source:** `docs/superpowers/plans/2026-07-14-models-pane-and-fixes.md` (T9–T11)

---

### Phase 4: Running-Server Observability UI

**Goal:** Surface the three observability backends that shipped in v0.13.1 with no UI.
Cheapest high-value work in the audit.
**Depends on:** Phase 1 (styles land first, so panels are built in the new idiom)
**Research:** Unlikely (endpoints exist and are tested)

**Scope:**
- **[M2.2]** Crash-watchdog surfacing: badge crashed servers + `oom_likely`, last stderr lines, restart
- **[M2.1 + M2.3]** Live server metrics panel: `GET /api/servers/{id}/metrics` (KV usage, slots, decode t/s, RSS, GPU bytes) — currently rendered as a single line. M2.3 is the per-process memory half of the same payload
- **[M2.4]** Log tail panel: `GET /api/servers/{id}/logs`
- "Rescan models" button for `POST /api/profiles/scan` — registration otherwise runs only at startup

**Source:** `docs/2026-07-14-audit.md` §3

---

### Phase 5: Frontend Module Split

**Goal:** `app.js` and `styles.css` become editable again. Covers **M5.1** (frontend modularization) and the structural half of **M3.2**.
**Depends on:** **Phase 1 must land first** — splitting a 4.1k-line stylesheet while a
restyle is uncommitted would be a merge disaster.
**Research:** Unlikely

**Scope:**
- Split `app.js` (3,816 lines) into ES modules: `api.js`, `state.js`, `panels/*`, `modals.js`, `palette.js`, `util.js`; `index.html` loads `type="module"`
- Split `styles.css` (4,105 lines): tokens/theme, base layout, per-panel sheets
- Move panel code and panel styles together

**Source:** `docs/2026-07-14-audit.md` §1 (both marked [High])

---

### Phase 6: Release v0.17.0

**Goal:** Ship it.
**Depends on:** Phases 1–5
**Research:** Unlikely

**Scope:**
- CHANGELOG, version bump, tag, push
- Derive `index.html`'s cache-buster from `lcc_api.__version__` instead of the manual `?v=` bump

**Source:** `docs/superpowers/plans/2026-07-14-models-pane-and-fixes.md` (T12), `docs/2026-07-14-audit.md` §4

## Backlog (Not Scheduled)

Carried from the retired planning docs; promote into a phase when a milestone picks them up.

**Refactors (audit §1, Medium/Low):**
- Extract FastAPI routers from `lcc_api/app.py` (680 lines) — profiles / servers / models+HF / system / estimates
- Split `lcc_core/server_manager.py` (1,128 lines) → `server_state.py`, `process_utils.py`, `vllm_wsl.py`
- `lcc_core/estimates.py` (998) + `hardware.py` (994) — only when next touching them

**Optimizations (audit §2):**
- Double model scan in `profile_registry.register_discovered_models` — `resolve_profiles()` already calls `discover_models()`
- TTL cache on `/api/profiles` (reuse the 2s lock+TTL pattern from `/api/system/live`)
- `AppConfig.load()` re-reads config.json per endpoint — mtime-checked cached loader
- Startup autoscan blocks the ASGI lifespan — move to a background task

**Features:**
- **[M4.1]** Quant picker: repo file listing × `fit.py` verdict per quant
- **[M4.4]** Ollama integration — discovery, launch/status, pulls, updates
- **[M5.3]** OpenCode provider auto-sync on start/stop (avoids manual JSONC edits)
- **[M5.2]** TPS calibration against real benchmarks (ongoing since v0.6.0). Phase 3 T11 calibrates vLLM specifically; this is the general case
- Runtime apply-update button (open: no safe universal updater)

**Design:**
- Obsidian Rail GUI overhaul — near-black `#0c0d0f`, 1px hairlines at 8% white, Inter + Geist Mono, electric mint `#5fe3b1` on active/CTA/focus. Replaces the current token world (do not mix). Explicitly out of scope for the instrument-console IA pass.

**Carried from REVIEW_MILESTONES M1–M5** (full detail in `docs/archive/REVIEW_MILESTONES.md`):

*Reliability (M1):*
- M1.4 — Structured error classification from subprocesses/launches. Port conflict, OOM-likely, missing binary etc. as categories surfaced in API responses, instead of generic errors. `server_manager.py`, `fit.py`, `backends.py`, `app.py`
- M1.5 — Centralize defaults and magic numbers into a constants module so UI (`PARAM_DEFAULTS`) and backend stay in sync. `config.py`, `estimates.py`, `smart_tune.py`, `server_manager.py`, `app.js`

*Observability (M2):*
- M2.5 — Strong running-state indicators across the UI: profiles table shows which profile has an active server (+ Stop), parameters inspector reflects live state. *Medium-High*

*Debt + UX (M3):*
- M3.1 — Extract KV cache ladders, pricing tables, and GPU markers into one source of truth with llama.cpp block-layout comments. Currently duplicated across `estimates.py` / `smart_tune.py`
- M3.2 — Frontend concurrency hygiene: abort controllers or sequence tokens to guard overlapping refreshes. *Pairs with Phase 5*
- M3.3 — Richer empty states + first-run onboarding with real CTAs. *Note: `tests/test_empty_copy.js` suggests this is already being touched in the current WIP*
- M3.4 — Parameters editor: dirty/unsaved indicator, revert-to-last-saved / last-fit / defaults, progressive disclosure for advanced fields
- M3.5 — Accessibility: `aria-live` for server started/stopped/crashed, consistent loading skeletons, focus management and contrast
- M3.6 — Table enhancements: client-side sorting on Profiles/Models, persist filter state, clearer running badge
- M3.7 — Standardize the `_run` subprocess wrappers scattered across `hardware.py`, `backends.py`, `server_metrics.py`

*Features + platform (M4/M5):*
- M4.2 — Improve draft-model + speculative-decoding workflow (`draft_models.py`, UI suggestions, fit integration). *Overlaps Phase 2 — sequence after it*
- M5.4 — Broader platform testing & CI improvements

> **M4.3** ("other high-value items from ROADMAP / TODO") was a pointer, not a work item —
> the docs it pointed at are now this file. Nothing to carry.
