---
description: "Llama Control Center — current position and accumulated context"
type: ProjectState
about: "llama-control-center"
---

# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-08-21)

**Core value:** Operators can see whether a local model actually fits this machine before they launch it — and watch it once it runs.
**Current focus:** v0.17.0 — Close the Open Loops, Phase 5 (Frontend Module Split)

## Current Position

Milestone: v0.17.0 — Close the Open Loops (0.17.0)
Phase: 5 of 6 (Frontend Module Split) — phases 3 and 4 taken out of order by choice
Plan: 05-01 applied (05-02 covers the CSS, not yet written)
Status: Applied — T1–T4 done, awaiting the human-verify checkpoint
Branch: feat/frontend-module-split (from main @ 190fd74)

⏸ Phase 2 is complete in code but parked on its human-verify checkpoint: the embedded-MTP
launch path is proven against `--help` and upstream source at the build commit, but not by
a running server. Issue #14 stays open until it is.
Last activity: 2026-08-22 — 05-01 applied: app.js 5,222 → 472 across 25 modules; boot bug found by the operator, fixed, and guarded

Progress:
- Milestone: [████░░░░░░] 42% (2 complete, 1 of those awaiting its own verify)
- Phase 5: [███████░░░] 70% (05-01 code-complete, human-verify open; 05-02 not written)

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ○     [05-01 applied, awaiting human-verify]
```

## Accumulated Context

### Uncommitted work at init time — ✅ resolved, kept for the lesson

PAUL was initialized while **20 files were uncommitted** on `feat/terminal-instrument-design`:
`TODO.md`, `lcc_api/app.py`, `lcc_api/static/{app.js,index.html,styles.css}`,
`lcc_core/{hf_metadata,profile_registry,profile_resolver,smart_tune}.py`, `models.json`,
`tests/test_{hf_metadata,lcc_api,lcc_core,profile_registry}.py`, plus untracked
`DESIGN.md`, `PRODUCT.md`, and four new node tests.

Only `.paul/` was committed at init — that WIP was deliberately left untouched. It has
since landed (`820e873`, `cb1818f`, `ad85599`); `models.json` is the one file deliberately
left **permanently uncommitted**, because this is a public repo and it is a machine
inventory.

⚠️ **This repo has already lost work this way once:** `b4e818a revert: un-commit operator
WIP swept into b961153`. Any PAUL command whose workflow ends in a commit (notably
`/paul:map-codebase`) must stage explicit paths, never `git add -A`, until the tree is clean.

### Planning doc migration (2026-08-21)

The project had **three overlapping planning docs** that disagreed with each other —
`TODO.md` pointed at `REVIEW_MILESTONES.md`, while `docs/2026-07-14-audit.md` §4 recorded
that `REVIEW_MILESTONES.md` was already stale. All are now consolidated into
`.paul/ROADMAP.md`:

| Source | Disposition |
|---|---|
| `ROADMAP.md` (177 lines) | Archived → `docs/archive/`. Shipped items → PROJECT.md; open items → phases/backlog |
| `REVIEW_MILESTONES.md` (331 lines, M1–M5, 22 open) | Archived → `docs/archive/`. Content folded into phases 4–5 + backlog |
| `TODO.md` (6 open, 41 done) | **Left in place — it has an uncommitted edit.** Content already migrated (incl. the uncommitted Obsidian Rail item). Retire after the WIP lands. |
| `docs/2026-07-14-audit.md` | Kept as a reference document. Its priorities drive phases 4–5 and the backlog. |
| `docs/superpowers/plans/*` | Kept as historical execution records. Two are complete (shell-code-removal → v0.16.0, ground-truth-layer → merged `a1a6444`); the models-pane plan supplies phases 2–3 and 6. |

### Known traps

- **Issue #14 is fixed in code, unproven on hardware.** Both halves landed: discovery
  (`DRAFT_NAME_RE` → `_is_draft_model()`, `cb1818f`) and launch (`_has_builtin_mtp()` in
  `profile_resolver.py`, `0d11c95`). The issue stays open only for Phase 2's human-verify:
  no embedded-MTP model has actually been launched through the fixed path yet.
- **`tools/llama.cpp-source` is ~4 months behind the installed binary.** That drift is how
  `SPEC_TYPES` silently went stale. Check flag vocabularies against `llama-server --help`
  from the *installed* build, never against the vendored source.
- ~~**Phase 5 must not start before Phase 1 lands**~~ — Phase 1 landed in `83f957b`, so the
  split is unblocked. `app.js` is 5,222 lines and `styles.css` 4,227.
- Test suite needs `encoding="utf-8"` for node subprocess output. Baseline: **258 passed,
  2 skipped, 16 node subtests**. Node tests are picked up by glob — dropping a
  `tests/test_*.js` in is enough, no driver edit.
- ⚠️ **Every node test scrapes the source file it tests** (`indexOf('function x')`,
  regex, brace counting, then `vm`/`eval`). Six read `app.js`, one reads `styles.css` +
  `index.html`. Any file split breaks them; plan 05-01 converts the six to real imports.
- ⚠️ **`styles.css` is cascade-ordered.** It ends in two override layers that win by
  being last — dark component overrides (3365) and the terminal-instrument pass (3903).
  Reordering them degrades the Phase 1 restyle silently.
- ⚠️ **Any module-scope DOM/window read breaks node importability for the whole graph.**
  It works in the browser (modules run after parsing), so nothing catches it but the tests.
  Query inside a function instead. Two shipped this way and were fixed in 05-01.
- ⚠️ **`tests/test_app_boots.js` is the only check that the app actually boots.** Do not
  delete it when the CSS split or a later refactor makes it inconvenient.
- ⚠️ **ES module imports are live but read-only.** Cross-module mutable state must move
  behind setters or into `state.js`, or it throws at runtime rather than failing cleanly.
- The venv is **uv-made and has no pip**: install with
  `VIRTUAL_ENV=.venv uv pip install <pkg>`. Scope pytest to `tests/` — a bare `pytest`
  collects the gitignored `graphify/` and breaks.
- `index.html` cache-buster (`?v=0.15.0`) is bumped by hand each release — already lagging 0.16.0.

### Codebase map

`.paul/codebase/` holds STACK, ARCHITECTURE, STRUCTURE, CONVENTIONS, TESTING, INTEGRATIONS,
CONCERNS (mapped 2026-08-21 against `feat/terminal-instrument-design`). Read CONCERNS before
planning any phase — it carries the load-bearing traps.

Mapped inline rather than via the workflow's 4 parallel Explore agents. Two claims inherited
from `docs/2026-07-14-audit.md` were checked and found **stale**, so don't quote that doc
without verifying: `app.js` is 5,060 lines (audit said 3,816), and the `index.html`
cache-buster is `?v=0.16.17` against `__version__` 0.16.0 (audit said `?v=0.15.0`).

## Session Continuity

**Next action:** walk the dashboard against 05-01's human-verify checkpoint, then plan
05-02 (the CSS split).

⚠️ **05-01 shipped a dead app once.** `wireEvents` was partitioned by selector, which
separated `const palBack = $('#command-palette')` from the `if (palBack)` that used it; the
ReferenceError at boot killed every listener. Fixed, and guarded by
`tests/test_app_boots.js`. **The lesson is that green tests said nothing about whether the
app ran** — parse checks, import checks, line-survival checks and 258 passing tests were
all true while the dashboard was inert. Treat "the suite is green" as evidence about
functions, not about the product.

**Still open:**
- **Issue #14** stays open until Phase 2's human-verify: launching a real embedded-MTP
  model and confirming the server comes up without a `draft_model`. Needs the 5090 free.
- **Repo tidy-up**: nine local branches and eight remote ones, most from finished work.
  Wants a propose-then-apply list, not a sweep.
- ~~PR #15~~ closed 2026-08-22 with an explanation — it documented the limitation
  `0d11c95` removed.
