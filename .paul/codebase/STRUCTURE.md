---
description: "Llama Control Center — codebase structure"
type: CodebaseDoc
about: "llama-control-center"
---

# Codebase Structure

## Directory Layout

```
llama-control-center-repo/
├── .paul/                  PAUL planning (PROJECT, ROADMAP, STATE, paul.toml, codebase/)
├── lcc_api/                transport layer
│   ├── app.py              FastAPI app — 41 routes, 13 Pydantic models, lifespan
│   ├── __main__.py         python -m lcc_api
│   └── static/             app.js (5,060) · styles.css (4,156) · index.html (733)
├── lcc_core/               portable domain core — no HTTP knowledge
│   └── truth/              gguf.py · kv.py · shadow.py — ground-truth memory layer
├── tests/                  pytest (219 tests) + 6 .js files run via node subprocess
├── docs/
│   ├── 2026-07-14-audit.md      refactor/optimization priorities — still current
│   ├── archive/                 retired planning docs (ROADMAP, REVIEW_MILESTONES)
│   └── superpowers/{plans,specs}/  historical execution records
├── mcps/                   MCP server bits
├── scripts/                capture_goal_evidence.py
├── models.json             profile manifest — explicit model_path, no script fields
├── start-lcc.py / stop-lcc.py
└── TODO.md, CHANGELOG.md, README.md, PRODUCT.md, DESIGN.md
```

## Directory Purposes

| Path | Purpose | Rule of thumb |
|---|---|---|
| `lcc_core/` | All domain logic | Must stay importable without FastAPI |
| `lcc_core/truth/` | Facts derived from artifacts, not tuned constants | `kv.py` is explicitly pure — no I/O, no globals, no clock. Keep it that way |
| `lcc_api/` | HTTP transport + static serving | Thin: parse → call core → return |
| `lcc_api/static/` | The dashboard | No build step; edit the files directly |
| `tests/` | Flat — no subdirectories | One `test_<module>.py` per core module |
| `docs/archive/` | Retired docs | Do not add new work here |

## Key File Locations

| Looking for | File |
|---|---|
| A route | `lcc_api/app.py` (all 41 live here) |
| Memory/fit math | `lcc_core/estimates.py`, `lcc_core/truth/kv.py` |
| GGUF header reading | `lcc_core/truth/gguf.py` |
| Why a model wasn't discovered | `lcc_core/profile_registry.py` (`DRAFT_NAME_RE`) |
| Why a profile won't launch | `lcc_core/profile_resolver.py` |
| Auto-tune search | `lcc_core/smart_tune.py` |
| Process start/stop/crash | `lcc_core/server_manager.py` |
| Live metrics polling | `lcc_core/server_metrics.py` |
| Hardware probes | `lcc_core/hardware.py` |
| Frontend state | `lcc_api/static/app.js` — module-global `state` at line 1 |
| Param defaults | `app.js` `PARAM_DEFAULTS`, mirrored server-side (M1.5 wants these unified) |
| Command palette | `app.js` `COMMAND_REGISTRY` |

## Naming Conventions

- Core modules are **flat, singular, domain-named**: `fit.py`, `estimates.py`, `hardware.py` — not `fit_service.py`
- Runtime-specific arg builders are suffixed `_args`: `llama_args.py`, `vllm_args.py`
- Tests mirror modules: `lcc_core/profile_registry.py` → `tests/test_profile_registry.py`
- The `truth/` package is the one nested namespace — used for the ground-truth layer only
- Pure-helper JS extracted for testing keeps a descriptive verb name: `formatServerMetricsLine`, `buildPortableExportSnapshot`

## Where to Add New Code

| Adding | Goes in |
|---|---|
| Domain logic | A `lcc_core/` module. If it needs a request object, it's in the wrong layer |
| An endpoint | `lcc_api/app.py` + a Pydantic model beside it (until the router split lands) |
| Memory arithmetic | `lcc_core/truth/kv.py` — keep it pure, no I/O |
| A new runtime | A `<runtime>_args.py` + a branch in `server_manager.py` launch/stop |
| Frontend behaviour | `app.js`. Extract pure helpers to module scope so a `.js` test can import them |
| A test | `tests/test_<module>.py`. **JS tests must be wired into a pytest driver or they never run** |

## Special Directories

- **`docs/superpowers/`** — plans and specs from prior execution passes. Historical record, not active planning; two of the four plans are complete
- **`docs/archive/`** — retired planning docs with deprecation banners; superseded by `.paul/ROADMAP.md`
- **`.paul/`** — the active planning system
