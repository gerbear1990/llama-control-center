---
description: "Llama Control Center — current position and accumulated context"
type: ProjectState
about: "llama-control-center"
---

# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-08-21)

**Core value:** Operators can see whether a local model actually fits this machine before they launch it — and watch it once it runs.
**Current focus:** v0.17.0 — Close the Open Loops. Phase 4 complete; next is Phase 3 or 5.

## Current Position

Milestone: v0.17.0 — Close the Open Loops (0.17.0)
Phase: 4 of 6 (Running-Server Observability UI) — ✅ complete, taken ahead of 3 by choice
Plan: 1 of 1 in current phase (04-01) — done
Status: Unified — human-verify approved in a browser 2026-08-21
Branch: feat/observability-ui (from main @ 83f957b) — ⚠️ not yet pushed, no PR open

⏸ Phase 2 is complete in code but parked on its human-verify checkpoint: the embedded-MTP
launch path is proven against `--help` and upstream source at the build commit, but not by
a running server. Issue #14 stays open until it is.
Last activity: 2026-08-21 — Phase 4 verified and closed out (`03975cc`); SUMMARY written

Progress:
- Milestone: [████░░░░░░] 42% (2 complete, 1 of those awaiting its own verify)
- Phase: [██████████] 100% (5 of 5 tasks)

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ◉     [Unifying — Phase 4 done, awaiting push/PR]
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

**Next action:** push `feat/observability-ui` and open its PR, then `/paul:plan` for
Phase 5 (frontend module split) — now unblocked, since Phase 1's restyle has landed and
every `tests/*.js` runs in the suite.

**Two open decisions carried forward:**
- **PR #15** is still open and must **not** be merged — it documents the embedded-MTP
  limitation that `0d11c95` fixed. Close it or rewrite it as a note.
- **Issue #14** stays open until Phase 2's human-verify: launching a real embedded-MTP
  model and confirming the server comes up without a `draft_model`.
