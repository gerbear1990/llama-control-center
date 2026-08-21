---
description: "Llama Control Center — current position and accumulated context"
type: ProjectState
about: "llama-control-center"
---

# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-08-21)

**Core value:** Operators can see whether a local model actually fits this machine before they launch it — and watch it once it runs.
**Current focus:** v0.17.0 — Close the Open Loops, Phase 2 (Embedded-MTP Support)

## Current Position

Milestone: v0.17.0 — Close the Open Loops (0.17.0)
Phase: 2 of 6 (Embedded-MTP Support)
Plan: 1 of 1 in current phase (02-01)
Status: Planning — plan written, awaiting approval
Last activity: 2026-08-21 — WIP landed (cb1818f, 820e873, ad85599); Phase 1 complete; Phase 2 planned

Progress:
- Milestone: [█░░░░░░░░░] 17% (1 of 6 phases)
- Phase: [░░░░░░░░░░] 0%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ◉        ○        ○     [Planning]
```

## Accumulated Context

### Uncommitted work at init time — read before planning Phase 1

PAUL was initialized while **20 files were uncommitted** on `feat/terminal-instrument-design`:
`TODO.md`, `lcc_api/app.py`, `lcc_api/static/{app.js,index.html,styles.css}`,
`lcc_core/{hf_metadata,profile_registry,profile_resolver,smart_tune}.py`, `models.json`,
`tests/test_{hf_metadata,lcc_api,lcc_core,profile_registry}.py`, plus untracked
`DESIGN.md`, `PRODUCT.md`, and four new node tests.

Only `.paul/` was committed at init — that WIP was deliberately left untouched.

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

- **Issue #14 is half-fixed, and the fix is uncommitted.** The discovery half
  (`DRAFT_NAME_RE` → `_is_draft_model()` in `profile_registry.py`) is done **in the working
  tree only** — `git show HEAD:lcc_core/profile_registry.py` still has the old regex, so
  discarding that WIP reintroduces the bug. The launch half is untouched: `profile_resolver.py`
  still demands `draft_model` for any profile with "mtp" in its text. Phase 2 lands both.
  Workaround meanwhile: `POST /api/profiles/save` with "MTP" absent from mode/name/description.
- **Phase 5 must not start before Phase 1 lands** — splitting a 4,105-line stylesheet while
  a restyle is uncommitted is an avoidable merge disaster.
- Test suite needs `encoding="utf-8"` for node subprocess output. Baseline: 151 passed + 1 skipped.
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

**Next action:** `/paul:plan` for Phase 1, or commit the in-flight `feat/terminal-instrument-design`
work first so Phase 1 starts from a clean tree (recommended).
