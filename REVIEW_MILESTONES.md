# LCC Code Review — Milestones & Tracking

**Review Date**: 2026-07-09  
**Branch at review**: `codex/smart-fit-kv-cache-tuning` (after `git pull`)  
**Review Scope**: Full top-to-bottom engineering review + dedicated UI/UX review of the Llama Control Center (LCC) project.  
**Source Review**: Comprehensive analysis covering architecture, code quality, performance, reliability, error handling, testing, UI/UX, accessibility, and more.  
**Related Docs**: [TODO.md](./TODO.md), [ROADMAP.md](./ROADMAP.md), [CHANGELOG.md](./CHANGELOG.md)

This document turns the review findings into **trackable, chunked work** with clear milestones, priorities, and success criteria.

---

## Milestone Overview

| Milestone | Theme                              | Focus Areas                          | Priority     | Est. Size | Status     |
|-----------|------------------------------------|--------------------------------------|--------------|-----------|------------|
| **M1**    | Reliability & Foundations          | Safety, Windows robustness, testing  | Critical/High| Small–Med | In Progress (M1.3 + tests) |
| **M2**    | Running Server Observability       | Close the post-launch gap            | High         | Medium–Large | In Progress (core wiring + UI surfacing) |
| **M3**    | Polish, Debt & UX Quick Wins       | Maintainability + user friction      | Medium       | Medium    | Planned    |
| **M4**    | Feature Expansion                  | High-value product capabilities      | Medium       | Large     | Planned    |
| **M5**    | Strategic & Long-term              | Architecture evolution & calibration | Low–Medium   | Large     | Future     |

**Guiding Principles for Work**
- Ship small, valuable, testable increments.
- Every milestone should improve either **reliability** or **user-visible value**.
- Update this doc, TODO.md, and ROADMAP.md as items complete.
- Add or update tests for anything in M1/M2.
- Reference specific files from the review when implementing.

---

## M1: Reliability & Foundations (Critical / High)

**Goal**: Remove data-loss risks and platform fragility. Establish a stronger safety net before building new features on top.

**Key Outcomes**
- No path can silently wipe or corrupt `models.json`.
- Process/port detection is reliable across Windows configurations.
- Core reliability paths are better tested.
- Clearer error information reaches the UI.

### M1 Backlog

- [x] **M1.1** Enforce `load_manifest_safely` in **all** read paths  
  Completed: `load_profiles` now delegates to safe loader; ManifestReadError
  surfaced and handled in API endpoints, CLI, launch autoscan, prepare/launch
  paths, and inventory. (Tests for safe loader + error paths present in tree.) (2026-07-09)  
  **Files**: `lcc_core/manifest.py`, `profile_resolver.py`, `inventory.py`, `launch_scripts.py`, any other callers of `load_manifest`.  
  **Why**: Critical recent fix (see server_manager + save paths) is incomplete. Unsafe `load_manifest` still exists.  
  **Priority**: Critical

- [x] **M1.2** Centralize and harden Windows process & port detection  
  Completed: Extracted robust helpers using psutil (preferred) + improved
  fallbacks for netstat/tasklist. `pid_is_running`, `find_process_on_port`,
  and `_port_in_use_info` updated with better parsing. start-lcc/stop now
  delegate to shared impl in server_manager. CSV parsing for tasklist names.
  (2026-07-09)  
  **Files**: `start-lcc.py`, `stop-lcc.py`, `lcc_core/server_manager.py` (`pid_is_running`, `find_process_on_port`, netstat/tasklist parsing).  
  **Why**: Brittle string splitting and index-based parsing is fragile on non-English locales, IPv6, Docker/Hyper-V port exclusions.  
  **Priority**: High

- [x] **M1.3** Expand test coverage for reliability surfaces  
  Completed: Added 8+ new direct unit tests exercising manifest non-dict / non-list failures (via load_profiles + safely), additional watchdog transitions (starting->crashed), server_metrics error paths (no server, dead pid), port/process edge cases (high port, negative/huge pids), and API-level injected state tests for /metrics + /logs. All call real shipped functions (no reimpl). Full suite passes (151 tests in capture run with new committed launch smoke + metrics stub tests). (2026-07-09)  
  **Files**: `tests/test_lcc_core.py` (ManifestTests, ProcessPortDetectionTests, ServerCrashWatchdogTests, PerProcessMemoryTests), `tests/test_lcc_api.py` (ApiSmokeTests + new ServerMetricsLogsInjectedStateTests + MetricsSuccessWithStubTests), `tests/test_launch_smoke.py`.  
  **Priority**: High

- [ ] **M1.4** Improve structured error classification from subprocesses and launches  
  **Files**: `lcc_core/server_manager.py`, `fit.py`, `backends.py`, `lcc_api/app.py`, launch error paths.  
  **Why**: Many launch/fit failures surface as generic errors.  
  **Approach**: Introduce clearer error categories (port conflict, OOM likely, missing binary, etc.) and surface them in API responses.  
  **Priority**: Medium  
  **Status**: To Do

- [ ] **M1.5** Centralize defaults and magic numbers  
  **Files**: `lcc_core/config.py`, `estimates.py`, `smart_tune.py`, `server_manager.py`, `app.js` (PARAM_DEFAULTS), docs.  
  **Approach**: Create a small constants / defaults module or documented section. Make sure UI and backend stay in sync.  
  **Priority**: Medium (quick win inside M1)  
  **Status**: To Do

**M1 Success Criteria**
- All `models.json` reads use the safe loader. (M1.1 done.)
- Windows port/PID logic passes tests and handles documented edge cases. (M1.2 done.)
- Core reliability paths are better tested (M1.3 + strategy restructure: committed launch smoke test (AC4, Uvicorn + /servers on real state, run twice; now also calls /metrics and /logs on real tracked ids from state) + metrics stub success test in suite for full live data body; full discover passes (exact count from capture script)).
- `python -m unittest discover -s tests -q` passes.
- No silent data-loss vectors remain in manifest handling.

---

## M2: Running Server Observability (Highest Product Impact)

**Goal**: Users should have excellent visibility and control **after** they click Start — not just before.

This is currently the largest UX gap. The backend work (v0.13.x / unreleased) is largely complete:
- `GET /api/servers/{id}/metrics`
- Crash watchdog + `oom_likely`
- Per-process memory (psutil + nvidia-smi)
- Live host hardware
- stderr_log paths

The UI still needs to surface it.

### M2 Backlog

- [ ] **M2.1** Live Server Metrics UI  
  **Description**: Render KV-cache usage ratio, KV tokens, active/processing slots, prompt & predicted tokens/sec, context fill, health status from the metrics endpoint.  
  **Location**: Enhance `#servers` panel and/or inspector. Poll only when visible/expanded (pause on hidden tab).  
  **Files**: `lcc_api/static/app.js`, `lcc_api/static/index.html`, `styles.css` (new cards/gauges).  
  **Priority**: High  
  **Status**: In Progress (polling + basic metrics line + summary values wired in renderServers; full gauges follow)

- [ ] **M2.2** Crash / Exit Watchdog Surfacing + Restart  
  **Description**: Show "Crashed" badges, last stderr tail, `oom_likely` hint, and a Restart action.  
  **Files**: `server_manager.py` (already annotates), `app.js`, server list rendering.  
  **Priority**: High  
  **Status**: In Progress (crashed/oom badges + last_stderr snippet + Restart button + action wired; logs endpoint fixed + live)

- [ ] **M2.3** Per-Process Memory Visualization  
  **Description**: Show RSS (portable) + GPU VRAM attribution (NVIDIA) for tracked servers, preferably with simple bars or sparklines.  
  **Files**: Reuse data from `/metrics` endpoint + live hardware patterns.  
  **Priority**: High  
  **Status**: In Progress (RSS + GPU bytes surfaced in server panel via metrics.process; bars later)

- [ ] **M2.4** Proper Log Tail Viewer  
  **Description**: Dedicated (or expandable) view that tails the captured `stderr_log` / `stdout_log` for the selected tracked server. Support manual refresh + auto-follow when running.  
  **Files**: New or expanded Logs panel + backend endpoint if needed for tailing.  
  **Priority**: High  
  **Status**: To Do

- [ ] **M2.5** Strong Running-State Indicators Across UI  
  **Description**: Profiles table should clearly show which profile has an active server (with Stop button). Parameters inspector should reflect the live server.  
  **Files**: `app.js` profile rendering, server state syncing.  
  **Priority**: Medium-High  
  **Status**: To Do

**M2 Success Criteria**
- Starting a server immediately shows useful live data (not just "running").
- A crashed server is obvious with actionable next steps and recent logs.
- Users rarely need to leave the dashboard to debug a running (or recently failed) server.
- Polling is efficient (uses existing caches + visibility checks).

---

## M3: Polish, Debt Reduction & UX Quick Wins

**Goal**: Make the codebase easier to maintain and the product feel more polished and approachable.

### M3 Backlog

- [ ] **M3.1** Extract & centralize KV cache ladders, pricing tables, and GPU markers  
  **Files**: `lcc_core/estimates.py`, `lcc_core/smart_tune.py`.  
  **Why**: Dense duplicated lists for CACHE_LADDER, BF16/FP4 markers, ranks, weights. Hard to evolve safely.  
  **Approach**: Single source of truth table + helpers. Add comments referencing llama.cpp block layouts.  
  **Priority**: Medium  
  **Status**: To Do

- [ ] **M3.2** Frontend structure & concurrency hygiene  
  **Files**: `lcc_api/static/app.js` (large single file, global `state`).  
  **Approach**: Logical sections / extraction of renderers, API client, state updates. Add abort controllers or sequence tokens to guard overlapping refreshes and rapid profile switches.  
  **Priority**: Medium  
  **Status**: To Do

- [ ] **M3.3** Richer empty states and first-run onboarding  
  **Description**: When no models/profiles/runtimes: clear CTAs ("Add model folder", "Open Settings", "Generate example scripts"). Improve placeholders in Model Notes, Logs, Servers.  
  **Files**: `index.html`, `app.js`.  
  **Priority**: Medium  
  **Status**: To Do

- [ ] **M3.4** Parameters editor UX improvements  
  - Dirty / unsaved state indicator  
  - "Revert to last saved", "Revert to last fit", "Reset to defaults" actions  
  - Better progressive disclosure for advanced fields  
  **Files**: `app.js` param form handling.  
  **Priority**: Medium  
  **Status**: To Do

- [ ] **M3.5** Accessibility & live feedback improvements  
  - Add `aria-live` regions for major state changes (server started/stopped/crashed, refresh complete).  
  - Ensure consistent loading spinners/skeletons.  
  - Strengthen focus management and contrast if needed.  
  - Better error toasts with actionable suggestions where possible.  
  **Priority**: Medium  
  **Status**: To Do

- [ ] **M3.6** Table & filtering enhancements  
  - Optional client-side sorting on Profiles/Models tables.  
  - Persist more filter state.  
  - Clearer "running" column or badge.  
  **Priority**: Low–Medium  
  **Status**: To Do

- [ ] **M3.7** Subprocess wrapper standardization + better docs  
  **Files**: Various `_run` helpers across `hardware.py`, `backends.py`, `server_metrics.py`, etc.  
  **Priority**: Low–Medium  
  **Status**: To Do

**M3 Success Criteria**
- New contributors can find the main logic without getting lost in one giant file.
- Smart Fit / estimator internals are easier to evolve.
- First-time users have obvious next steps.
- The app feels more "finished" in day-to-day interaction.

---

## M4: Feature Expansion

**Goal**: Deliver high-leverage product features that build on the strong foundation.

### M4 Backlog (Prioritized)

- [ ] **M4.1** Quant / repo browser with fit verdicts  
  **Description**: For a selected HF repo (or local scan), list available quants, show estimated size + fit status (Good/Tight/Near Limit), allow one-click pull + register as profile.  
  **Why**: Directly addresses a long-standing roadmap item and a frequent user need.  
  **Related**: ROADMAP "Quant Selection" section.  
  **Priority**: High (within M4)  
  **Status**: To Do

- [ ] **M4.2** Improve draft model + speculative decoding workflow  
  **Files**: `draft_models.py`, UI suggestions, fit integration.  
  **Priority**: Medium  
  **Status**: To Do

- [ ] **M4.3** Other high-value items from ROADMAP / TODO  
  - Stronger runtime card actions (beyond recheck).  
  - Enhanced portability / script repair flows.  
  **Priority**: Medium  
  **Status**: To Do

- [ ] **M4.4** (Stretch) First-class support for another runtime (Ollama exploration)  
  **Note**: Keep scope small unless user demand is clear.  
  **Priority**: Low–Medium  
  **Status**: Future

**M4 Success Criteria**
- Users can discover and choose the right quant without leaving the tool.
- Common power-user workflows are faster and more guided.

---

## M5: Strategic & Longer-Term

- [ ] **M5.1** Evaluate lightweight frontend modularization or build step  
  **Trigger**: When `app.js` complexity or contributor friction becomes painful.  
  **Priority**: Low for now (vanilla has served well).  
  **Status**: Future

- [ ] **M5.2** Estimator calibration against real benchmarks  
  **Description**: Systematically compare Smart Fit + t/s estimates vs. measured results across model sizes, quants, and hardware. Feed learnings back into the model.  
  **Priority**: Medium (ongoing)  
  **Status**: Future

- [ ] **M5.3** Deeper downstream integrations  
  - Auto-sync tracked servers with tools like OpenCode (improve current manual wiring).  
  - Provider registration on Start/Stop.  
  **Priority**: Medium (demand-driven)  
  **Status**: Future

- [ ] **M5.4** Broader platform testing & CI improvements  
  **Priority**: Medium  
  **Status**: Future

---

## Quick Wins (Can be done in parallel with any milestone)

These are low-risk, high-perceived-value items:
- Add a few more contextual tooltips and inline hints.
- Make "Smart Fit" button label + tooltip even clearer about what it changes.
- Persist more UI preferences (e.g., last selected profile filter).
- Improve copy on error states and "Needs setup" metric.
- Add keyboard shortcut hints for Refresh (already has Ctrl+K for search).
- Small CSS spacing/alignment tweaks discovered during review.
- Update inline code comments that reference old version numbers or behavior.

---

## Cross-Cutting Concerns & Guidelines

- **Testing**: New backend behavior (M1/M2) requires tests. UI changes should at minimum have manual verification steps documented.
- **Docs**: Update README, ROADMAP, TODO, and CHANGELOG when shipping.
- **Performance**: Reuse existing caching patterns (see `server_metrics.py`, hardware live status). Avoid new polling storms.
- **Accessibility**: Follow existing patterns (aria, focus traps, sr-only, keyboard support).
- **Portability**: Changes must continue to work without hard-coded paths. Respect `LCC_*` env vars and user config/cache dirs.
- **Security**: Local-only tool — still avoid introducing new command-injection or path-traversal vectors when handling user-controlled paths/overrides.

---

## Recommended Chunking & Sequencing (from Review)

1. **M1 first** — prevents future pain and builds confidence.
2. **M2 next** — delivers the biggest user-visible leap given current backend investment.
3. **M3** — keep the codebase healthy while momentum is high.
4. **M4** — new features on a solid base.
5. **M5** — only when justified by usage or pain.

Many items in the existing ROADMAP.md "Running Server Tooling" section map directly to M2.

---

## How to Work With This Document

1. Pick an item and move it to "In Progress" (or add a date).
2. Create a focused branch / PR per item or small group of related items.
3. Update checkboxes here when complete.
4. Add a short entry to CHANGELOG.md under the next version.
5. Cross-link completed items back into TODO.md and ROADMAP.md (mark as shipped).
6. Revisit this document after each milestone to reprioritize.
(CHANGELOG.md already has the M1 reliability entries under [Unreleased].)

---

## Open Questions / Follow-ups

- Should we treat the current feature branch work (smart-fit KV tuning) as part of M1/M3 or land it separately?
- Any strong user demand signals for specific M4 items (quant picker vs Ollama vs something else)?
- Do we want to add a lightweight issue tracker mapping (GitHub issues/labels) to these milestone IDs?

---

**Next Step Suggestion**: Start with **M1.1** and **M1.2** (they are relatively self-contained, high leverage, and unblock other work cleanly).

---

## Current Focus (Edit this section as work progresses)

- **Active Milestone**: M1.3 complete; M2 observability surfacing in progress
- **M1.1 + M1.2 + M1.3**: safe manifest, hardened psutil pid/port, expanded reliability tests (manifest extra paths, watchdog, metrics unavailable, ports) + full suite passing. Logs endpoint fixed (P1). 
- **M2 progress**: /logs wired, metrics polling on refresh for running/crashed, renderServers now shows live KV/tps/slots, RSS/VRAM, crashed/oom badges + last_stderr + Restart action.
- **Next**: M1.4 error classification, M2 polish (gauges, full log tailer), M3.
- **Notes**:
  - Work on `codex/smart-fit-kv-cache-tuning`.
  - Primary entry `python -m lcc_api` + start-lcc.py start launch consistently; key endpoints return sane bodies.
  - See CHANGELOG [Unreleased] and plan.md for details.