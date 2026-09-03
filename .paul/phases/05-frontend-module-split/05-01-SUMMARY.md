---
phase: 05-frontend-module-split
plan: 01
subsystem: ui
tags: [es-modules, vanilla-js, refactor, node-test, boot-guard]

requires:
  - phase: 01-terminal-instrument-design
    provides: the restyle had to land before the frontend could be cut apart
  - phase: 04-observability-ui
    provides: the globbed node-test driver, which picked up the new boot guard with no registration
provides:
  - 25 ES modules under lcc_api/static/js/, one per panel plus shared systems
  - app.js reduced to an entry point (imports, command registry, global delegation, boot)
  - node tests that import real exports instead of scraping source text
  - tests/test_app_boots.js, a boot guard for the whole module graph
affects: [05-02-css-split, 06-release]

tech-stack:
  added: []
  patterns:
    - "native ES modules, no build step, no bundler, no dependency"
    - "each panel wires its own listeners in an exported init*(), called in order from app.js"
    - "command bodies are registered into palette.js rather than imported, to avoid a cycle"
    - "module scope stays free of DOM/window reads so every module is importable under node"

key-files:
  created: [lcc_api/static/js/*.js, lcc_api/static/js/panels/*.js, tests/test_app_boots.js]
  modified: [lcc_api/static/app.js, lcc_api/static/index.html, tests/test_*.js]

key-decisions:
  - "Split wireEvents by the element being wired, never by a selector named inside a handler"
  - "Global delegates (document.body click, document keydown) stay in app.js"
  - "Dropped the hand-bumped ?v= cache-buster; StaticFiles already sends etag/last-modified"
  - "Three leaf modules beyond the plan's five, so every converted test had a module to import from"

patterns-established:
  - "A new tests/*.js is picked up by existing"
  - "Any module-scope browser read is a defect: it breaks node importability for the whole graph"

duration: ~3h
started: 2026-08-22T00:05:00Z
completed: 2026-08-22T02:40:00Z
description: "app.js split from 5,222 lines into 25 ES modules; tests converted from source-scraping to real imports; boot guarded by a test after the split shipped a dead app"
type: Summary
about: "llama-control-center"
---

# Phase 5 Plan 01: Frontend Module Split Summary

**`app.js` went from 5,222 lines to 472 across 25 modules with no build step — and the
split shipped a completely dead dashboard first, which is the most useful thing in this
document.**

## Performance

| Metric | Value |
|--------|-------|
| Tasks | 4 auto + 1 decision checkpoint (answered "continue") + 1 human-verify (open) |
| Commits | 4 |
| `app.js` | 5,222 → 472 lines |
| Modules | 25 (largest: `panels/parameters.js`, 590 lines) |
| Suite | 258 passed, 2 skipped, **17** subtests (was 16) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Runs from modules, no build step | **Unverified in a browser** | Boots under a stubbed DOM; all 25 modules serve 200 as `text/javascript`; no bundler or dependency added. A human still has to look |
| AC-2: Tests import real exports | Pass | No test locates code by `indexOf('function ...')` any more. Two wiring checks still read source text *deliberately* — they assert that one function calls another, which an import cannot show — but they read the panel module that owns the code |
| AC-3: Entry point is thin | **Partial** | Every module is under the ~600 target. `app.js` is 472, not the under-300 the plan asked for |
| AC-4: Behaviour unchanged | Pass, with a caveat | The suite is green and no test was weakened. But the suite was *also* green while the app was dead, so this AC was worth much less than it appeared |

## What actually happened

**The split shipped an app that rendered and did nothing.** `wireEvents()` was partitioned
by the selector each statement names, which separated two `const` declarations from the
statements that use them:

```js
const palBack = $('#command-palette');       // matched the palette rule -> moved
if (palBack) palBack.addEventListener(...)   // names no selector -> stayed in app.js
```

Same for `hideNotInstalled` and the runtimes toggle. `palBack is not defined` threw during
boot, and a throw at boot kills every listener on the page.

**Every check in place passed while this was true.** Files parsed as ES modules; all 25
modules imported cleanly under node; every line of the original `wireEvents` still existed
somewhere; every `init*()` was called; all 258 tests were green; every module served 200
with the right MIME type. Not one of them ever ran the app's own boot sequence. The
operator found it by clicking.

The response was `tests/test_app_boots.js`: stub a DOM, import `app.js`, fail if evaluation
throws, and report the file and line. Bite-tested by reintroducing the exact shipped bug —
it fails the suite by name. It is not a browser and proves nothing about behaviour; it
answers the one question nothing was asking.

## Task Commits

| Task | Commit | Type | Description |
|------|--------|------|-------------|
| T1+T2: leaf modules + test conversion | `5ba3846` | refactor | 8 modules; 6 tests import real exports |
| T3+T4: systems, panels, wireEvents split | `5e708e6` | refactor | 25 modules; `app.js` → 482 |
| Boot repair + guard | `1d09ffd` | fix | reunite the orphaned blocks; add `test_app_boots.js` |
| Plan | `c210905` | plan | 05-01 |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Split `wireEvents` by the element being wired | The first pass matched any selector named *inside* a handler, which moved the 89-line `document.body` dispatcher into the runtimes panel and the global keydown into settings | Global delegates stay in `app.js`, where they belong |
| Commands registered, not imported | `palette.js` importing panels would be a cycle | `registerCommands()` seam; the palette needn't know what a command does |
| Three extra leaf modules (`launch`, `matching`, `tune`) | Without them, four of the six tests had no module to import from — which is what T2 exists to fix | Deviation from the plan's five, taken deliberately |
| Drop the `?v=` cache-buster | It cannot propagate across relative module imports, and `StaticFiles` already sends `etag`/`last-modified`. It was hand-bumped and already incoherent (`?v=0.16.17` vs `__version__ 0.16.0`) | One less thing to remember at release |
| Two module-scope browser reads made lazy | `panels/inventory.js` read `#metric-setup-wrapper`, `theme.js` called `window.matchMedia`, both at module scope. Fine in a browser, but they made their file and everything importing it unimportable under node | The whole graph is node-importable, which is what keeps the test conversion viable |

## Deviations from Plan

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 3 | One missing cross-module import (`copy.js` → `serverEndpoint`), two module-scope browser reads. All three would have been browser runtime errors |
| Scope additions | 2 | Three extra leaf modules; the boot guard |
| Missed | 1 | AC-3's 300-line target: `app.js` is 472 |

**On AC-3:** what remains in `app.js` is ~120 lines of global event delegation, a 64-line
command registry, imports and boot — genuinely "imports, wiring and boot" as AC-3
describes, but more of it than the 300-line estimate assumed. That number was written
before anyone had counted the delegation code. Moving the dispatcher to a `delegation.js`
would reach ~360 and buy nothing but a smaller number.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| **The split shipped a dead app** | Reunited the orphaned blocks; added a boot guard. See above |
| First `wireEvents` partition moved two global dispatchers into panels | Classify on the statement's first line — the element being wired |
| Statement splitter treated a closing `});` as a new statement | Rewrote it with bracket-depth tracking that ignores strings and comments |
| `copy.js` called `serverEndpoint` without importing it | Found by the first converted test, on its first run |
| Bash heredocs collapse `\\n` into a real newline before Python sees it | Recurring in this repo. Use the Write tool for content with escapes |

## Next Phase Readiness

**Ready:**
- 05-02 (CSS split) has a clean seam; `test_css_shell.js` was untouched and still guards the
  app-shell rule
- The boot guard means the CSS split cannot silently kill the app the same way

**Concerns:**
- **AC-1 is unverified.** A human still has to walk every panel. Given a listener bug already
  slipped through, the panels whose wiring moved deserve the most attention
- `panels/parameters.js` (590) and `panels/profiles.js` (558) are near the size limit
- Two tests still read source text on purpose. That is a legitimate use — asserting one
  function calls another — but it is coupled to source layout

**Blockers:** the human-verify checkpoint.

---
*Built with PAUL Framework v1.4 · https://chrisai.cv/skool · https://youtube.com/@chris-ai-systems*
*Phase: 05-frontend-module-split, Plan: 01*
*Completed: 2026-08-22*
