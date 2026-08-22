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
Phases: 2 of 6 complete (Phase 2 code-complete, parked on its human-verify)

## Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 1 | Terminal-Instrument Design Pass | 1 | ✅ Complete | 2026-08-21 |
| 2 | Embedded-MTP Support | 1 | ⏸ Awaiting human-verify | - |
| 3 | vLLM-WSL Fit Estimator + Auto-Tuner | TBD | Deferred (after 4) | - |
| 4 | Running-Server Observability UI | 1 | ✅ Complete | 2026-08-21 |
| 5 | Frontend Module Split | 2 | 🚧 Planning (05-01 created) | - |
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

**Goal:** Surface the observability data the backend already returns.
**Depends on:** Phase 1 ✅ (landed `83f957b`)
**Research:** Unlikely (endpoints exist and are tested)
**Plan:** `.paul/phases/04-observability-ui/04-01-PLAN.md`

⚠️ **Smaller than the audit says** — the terminal-instrument pass already built part of
this. Verified 2026-08-21: crash surfacing is **done**, metrics polling is **done**, the
metrics panel and log tail are **partial** (rendered as one line / a static preview), and
only the global rescan is genuinely **missing**.

**Scope:**
- ~~**[M2.2]** Crash-watchdog surfacing~~ ✅ **Already shipped** — `buildServerItemHtml` renders the crashed badge, `oom_likely` badge, a 300-char `last_stderr` snippet and a Restart button
- **[M2.1 + M2.3]** Live server metrics panel: `GET /api/servers/{id}/metrics` (KV usage, slots, decode t/s, RSS, GPU bytes) — currently rendered as a single line. M2.3 is the per-process memory half of the same payload
- **[M2.4]** Log tail panel: `GET /api/servers/{id}/logs`
- "Rescan models" button for `POST /api/profiles/scan` — registration otherwise runs only at startup

**Source:** `docs/2026-07-14-audit.md` §3

**Status:** ✅ Complete 2026-08-21 — landed as `03975cc`, verified in a browser by the
operator ("looks and performs much better"). Summary:
`.paul/phases/04-observability-ui/04-01-SUMMARY.md`. Suite: 258 passed, 2 skipped,
16 node subtests (up from 9 — the four orphaned `.js` files now run).

---

### Phase 5: Frontend Module Split

**Goal:** `app.js` and `styles.css` become editable again. Covers **M5.1** (frontend modularization) and the structural half of **M3.2**.
**Depends on:** Phase 1 ✅ (landed `83f957b`) — the restyle had to be in before the
stylesheet could be cut apart.
**Research:** Unlikely
**Split into two plans** (decided 2026-08-22): the two files have different risk profiles
and sharing a branch between them would make a bad merge unbisectable.

⚠️ **The audit's line counts are stale** — it says 3,816 / 4,105. Actual on 2026-08-22:
`app.js` **5,222**, `styles.css` **4,227**.

**Plan 05-01 — `app.js` → ES modules.** `.paul/phases/05-frontend-module-split/05-01-PLAN.md`
- `js/` leaf layer (util, api, state, copy, format), then shared systems, then one module
  per panel; `index.html` loads `type="module"`; `app.js` becomes a <300-line entry point
- **Converts the node tests from source-text scraping to real imports.** Six of the seven
  locate code with `indexOf('function ...')` / regex / brace counting and would break the
  instant anything moves. Not mentioned in any prior planning doc
- Favourable finding: **zero** inline `onclick=` handlers and **zero** `window.` globals,
  so module scoping cannot silently break event wiring

**Plan 05-02 — `styles.css` → per-concern sheets.** Not yet written.
- ⚠️ **Cascade order is the constraint.** The sheet ends in two override layers that win
  by being last — "Dark component overrides" (line 3365) and the "Terminal-instrument
  pass" (line 3903). Naive per-panel sheets reorder them and quietly degrade the restyle
  that Phase 1 just shipped
- `test_css_shell.js` reads `styles.css` by path and regexes rules out of it; it survives
  05-01 untouched but must be handled here

**Source:** `docs/2026-07-14-audit.md` §1 (both marked [High]) — verify before quoting

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

**Found during Phase 5 (2026-08-22) — operator-reported:**
- **Portability & Paths surfaces issues with no way to resolve them.** Scope agreed with
  the operator: guidance + a working checklist + a structured vocabulary. Three separate
  causes, all confirmed in the tree:
  1. **The fix text is already on the wire and thrown away.** `scan_portability_issues()`
     emits a `message` per issue ("User-specific absolute path should become an environment
     variable, config value, or relative path"); `renderIssues()` builds its text as
     `` `Line ${issue.line}: ${issue.value}` `` and never reads it. Same shape as the
     Phase 4 metrics gap.
  2. **Profile issues render raw machine tokens.** `[...missing, ...warnings].join(' | ')`
     puts internal identifiers on screen — an operator sees `model | param:ctx_size`.
  3. **The checklist is decorative.** The three `.check-item` rows in `index.html` are
     hardcoded with a permanent green `ok-dot`. The third claims "No absolute home paths in
     .ps1 / .json" while the list directly above it enumerates exactly those.
- Work: render the scanner's `message`; translate the closed vocabulary into sentences with
  a fix per kind; give each issue the control that resolves it (Edit roots / Open parameters
  / Select profile); drive the checklist from real state; **and change the resolver to emit
  structured issues (`{code, detail, fix}`) rather than strings the UI must pattern-match**
  — that touches `profile_resolver.py` and its tests, and helps the API too.
- The vocabulary is closed, which is what makes real guidance achievable:
  - `missing`: `model`, `draft_model`, `param:<key>`
  - `warnings`: low-confidence match, ambiguous match, draft model does not exist,
    could not read MTP support, MTP profile matched a non-MTP path, plus two from
    `manifest.py` — `recommended_params.<loc> contains an absolute path`, and
    `profile contains an absolute model path`

**Found during Phase 2 (2026-08-21):**
- **`_next_free_port` can't suggest anything on a default Windows host.** It only searches
  *upward*, and treats the dynamic range as reserved — but that range is 49152–65535 by
  default, so bumping past it leaves the port space entirely and returns None. The crash
  this caused is fixed; the unhelpfulness isn't. Searching below the dynamic range (or
  preferring the 8000–48000 band) would actually give the operator a usable port.
- **Fit under-counts a separate draft model.** `fit.build_fit_args()` never passes
  `draft_model`, so a profile using a companion draft file is estimated as if the draft
  weren't loaded — under-counting by roughly the whole draft model. (Embedded MTP is fine:
  those tensors are in the `-m` file and already priced.) Needs llama-fit-params to learn
  about the draft, not just a flag.
- **`SPEC_TYPES` drifted from the installed binary and nothing caught it.** It mirrored
  `tools/llama.cpp-source` (April, `71a81f6fc`) while the binary is build 10472
  (`60eeeb608`, August) — five `draft-*` values missing. Worth a startup check that
  reconciles known flag vocabularies against `llama-server --help`.

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
