---
phase: 04-observability-ui
plan: 01
subsystem: ui
tags: [vanilla-js, polling, metrics, logs, node-test, pytest-subtests]

requires:
  - phase: 01-terminal-instrument-design
    provides: the design token system (--rail, hairlines, monospace machine data) the new panels adopt
  - phase: 02-embedded-mtp
    provides: _is_draft_model(), which the global rescan exercises on every scan root
provides:
  - live metrics panel for the selected server, fed by the existing poll
  - following log tail with stdout/stderr separated
  - global "Rescan models" control
  - a globbed node-test driver, so every tests/*.js runs in the suite
affects: [05-frontend-module-split, 06-release]

tech-stack:
  added: []
  patterns:
    - "pure module-scope row builder + thin DOM renderer, so formatters are node-testable without a DOM"
    - "glob-and-subtest driver for node tests, replacing per-file registration"

key-files:
  created: [tests/test_metrics_rows.js]
  modified: [lcc_api/static/app.js, lcc_api/static/index.html, lcc_api/static/styles.css, tests/test_lcc_api.py]

key-decisions:
  - "Kept formatServerMetricsLine untouched; the panel is a second, denser view beside it"
  - "Absent metrics fields are dropped, not rendered as null/NaN — vLLM legitimately omits llama.cpp fields"
  - "Follow-mode pins to the bottom only when already at the bottom, so scrollback is not yanked"
  - "Node driver globs tests/test_*.js rather than listing them; exit code is the contract, `ok` checked only when present"

patterns-established:
  - "New polling UI reuses the live-hardware idiom: one interval, body bails while document.hidden"
  - "A new tests/*.js file is picked up by existing, not by registration"

duration: 23min
started: 2026-08-21T21:49:49Z
completed: 2026-08-21T22:12:00Z
description: "Running-server observability surfaced: metrics panel, following log tail, global rescan, and every orphaned node test wired into the suite"
type: Summary
about: "llama-control-center"
---

# Phase 4 Plan 01: Running-Server Observability UI Summary

**The dashboard no longer goes quiet after launch — the metrics payload it was already
fetching now has a panel, logs follow instead of snapshot, and a model dropped in
mid-session can be registered without a restart.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~23 min (plan commit → task commit) |
| Started | 2026-08-21T21:49:49Z |
| Completed | 2026-08-21T22:12:00Z |
| Tasks | 4 auto + 1 human-verify checkpoint |
| Files modified | 5 (+3 `.paul` bookkeeping) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Metrics panel shows what the payload carries | Pass | `buildServerMetricsRows()` emits KV (with ratio bar), slots, prompt/decode t/s, ctx, RSS, VRAM, CPU, health. Absent fields are omitted, not rendered |
| AC-2: The log tail follows | Pass | 2.5s poll while Follow is on; stdout and stderr are separate labelled streams; poll body bails while `document.hidden` |
| AC-3: A model dropped mid-session can be registered | Pass | `#models-rescan` → `POST /api/profiles/scan {}` → refresh; reports registered count, says "no new models" at zero |
| AC-4: New pure helpers are actually covered | Pass | Suite went from 9 to 16 subtests — the four orphaned `.js` files now run, plus the new one |

## Accomplishments

- **Nothing the payload carries is discarded any more.** The poll already fetched `health`,
  `props`, `cpu_percent` and the full `summary` map; `formatServerMetricsLine()` consumed a
  handful of fields into one card line and the rest was dropped on the floor. The panel is
  the detail view for what was already on the wire — no backend change, no extra request.
- **The four orphaned node tests run.** `test_css_shell.js`, `test_empty_copy.js`,
  `test_launch_lock.js` and `test_smart_fit_ui.js` passed when run by hand and were
  referenced by no driver, so they had never once run in CI. Adding a fifth test beside four
  dead ones would have entrenched exactly the rot this task existed to remove.
- **Global rescan, verified against real inventory.** A live `POST /api/profiles/scan` on
  this machine correctly skipped `gemma-4-26b-a4b-it-q8_0-mtp` as a draft companion, which
  independently re-validates Phase 2's `_is_draft_model()` against real filenames.

## Task Commits

Landed as one commit rather than four — the tasks share `app.js`/`index.html` hunks and
splitting them would have produced commits that don't stand alone.

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| T1: Global "Rescan models" control | `03975cc` | feat | `rescanModels()` + `initModelsRescan()`, header control in the Models panel |
| T2: Live metrics panel | `03975cc` | feat | `buildServerMetricsRows()` (pure) + `renderServerMetricsPanel()` |
| T3: Following log tail | `03975cc` | feat | `pollLogTail`/`startLogFollow`/`stopLogFollow`/`initLogFollow`, split streams |
| T4: Node-suite driver | `03975cc` | test | `NodeSuiteTests.test_every_js_test_passes` + `tests/test_metrics_rows.js` |

Plan metadata: `cc669bd` (plan 04-01)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `lcc_api/static/app.js` | Modified (+166) | Metrics rows builder + renderer, log tail follow, rescan |
| `lcc_api/static/index.html` | Modified (+29) | `#models-rescan`, `#log-follow`, `.log-streams` (`#log-preview` / `#log-stdout`), `#server-metrics` |
| `lcc_api/static/styles.css` | Modified (+71) | Panel, ratio bar and stream styling using existing tokens |
| `tests/test_metrics_rows.js` | Created | Full / sparse / unknown-health / empty payload cases |
| `tests/test_lcc_api.py` | Modified (+53) | Globbed node-suite driver using pytest subtests |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Keep `formatServerMetricsLine()` untouched | It is the right density for a list row and carries its own node test; the panel is a different view, not a replacement | Two formatters coexist by design; both tested |
| Omit absent fields rather than render placeholders | `server_metrics` returns null for llama.cpp-only fields on a vLLM server; "NaN%" on screen reads as a broken app, not an absent reading | Panel row count varies by backend — intended |
| Pin scroll only when already at the bottom | Yanking the view while the operator reads back through a stack trace is how follow modes become unusable | Follow is usable during an incident, not just idle |
| Driver globs instead of listing filenames | The next `.js` test should be picked up by existing | Prevents the orphan class of bug from recurring |
| Exit code is the contract; `ok` asserted only when present | `test_server_metrics_formatter.js` prints a formatted line instead of an `ok` field | Working tests were not rewritten to fit the driver |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 0 | — |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** Plan executed as written. The plan's own `<prior_findings>` had already
absorbed the corrections (crash surfacing and metrics polling were found already complete
before planning, contrary to `docs/2026-07-14-audit.md`), so execution had nothing to undo.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| First bite-test of the node driver was worthless — `process.exit(1)` was appended *after* the file's existing exit, so it never ran and the "pass" proved nothing | Redone by breaking a real assertion; the Python suite then failed naming the file, which is the actual contract |
| `test_server_metrics_formatter.js` has no `ok` field, so a strict driver would have failed a passing test | Relaxed the driver to treat exit code as the contract rather than rewriting a working test to suit it |

## Next Phase Readiness

**Ready:**
- Phase 5 (frontend module split) now has a clean seam to cut along: the pure row/format
  builders are module-scope and DOM-free, and each has node cover that will survive the move
- Every `.js` test runs, so the split has real regression cover instead of nominal cover

**Concerns:**
- `app.js` is now 5,222 lines. Phase 5 is the correct answer and is already scheduled
- The `index.html` cache-buster is still bumped by hand and still lags `__version__`

**Blockers:** None

---
*Built with PAUL Framework v1.4 · https://chrisai.cv/skool · https://youtube.com/@chris-ai-systems*
*Phase: 04-observability-ui, Plan: 01*
*Completed: 2026-08-21*
