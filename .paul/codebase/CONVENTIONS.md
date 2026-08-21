---
description: "Llama Control Center — coding conventions"
type: CodebaseDoc
about: "llama-control-center"
---

# Coding Conventions

## Naming Patterns

- Core modules: flat, singular, domain nouns — `fit.py`, `estimates.py`, `hardware.py`
- Runtime arg builders: `<runtime>_args.py` — `llama_args.py`, `vllm_args.py`
- Module-level constant tables: `SCREAMING_SNAKE` — `CACHE_BYTES`, `CACHE_LADDER`, `PARAM_DEFAULTS`, `COMMAND_REGISTRY`
- Private helpers: leading underscore — `_BF16_CACHE_LADDER`, `_store_meta_cache`, `_run`
- Predicates read as questions: `model_has_builtin_mtp`

## Code Style

- **`from __future__ import annotations` in 24 of 25 core modules.** Match it in new modules.
- Modern builtin generics in annotations: `dict[str, float]`, not `Dict[str, float]`
- `@dataclass` for structured values (8 modules use it) — `ArchFacts`, config, resolver/registry results. Reach for a dataclass before a bare dict.
- No linter or formatter config in the repo — match surrounding style rather than reformatting

## Import Organization

Stdlib → third-party → local relative, blank-line separated, as in `lcc_core/truth/kv.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from .gguf import ArchFacts
```

Relative imports inside the `truth/` package; absolute `lcc_core.*` elsewhere.

## Error Handling

- **Core** raises or returns structured results; it does not know about HTTP
- **API** converts to `HTTPException` — currently 17× `400` and 2× `404` in `lcc_api/app.py`. That flatness is deliberate-by-accident and is audit item M1.4: real categories (port conflict, OOM-likely, missing binary) are wanted
- **Probes degrade, never explode.** Hardware and runtime-update paths are best-effort: `runtime_updates.py` is documented as "best-effort ... against public release sources", and the NVIDIA path in `/api/system/live` has a one-shot graceful disable. A missing `nvidia-smi`, `lspci`, or `system_profiler` must produce a partial answer, not a 500

## Logging

**There is no logging framework in `lcc_core/` or `lcc_api/`** — no `import logging` anywhere in either package. Diagnostics travel as:

- structured data in API responses (e.g. the `process` block, `oom_likely`)
- captured subprocess stderr written to per-server log files, exposed via `GET /api/servers/{id}/logs`
- `print()` in the operator-facing entry point only (`start-lcc.py`, 25 calls); core modules use it barely (4 modules, once each)

Don't introduce `logging` casually — either follow the structured-response convention or raise it as a deliberate change.

## Comments

Comments explain **why the number is that number**, which matters in a codebase full of memory arithmetic. The house style is to cite the upstream derivation:

```python
# Bytes per stored element by KV cache type, mirroring estimates.CACHE_BYTES
# exactly (see that table's comment for the ggml block-struct derivation).
# Quantized types carry block scales, so q8_0 is 8.5 bits (1.0625 B), not 1.0.
```

Module docstrings state the contract, including negative constraints:
`"Memory arithmetic over ArchFacts. Pure: no I/O, no globals, no clock."`

## Function Design

- Pure functions where the domain allows it — `truth/kv.py` is the reference case, and its purity is load-bearing for testability
- Subprocess calls funnel through per-module `_run` helpers (standardizing these across `hardware.py`, `backends.py`, `server_metrics.py` is audit item M3.7)
- Frontend: pure helpers are lifted to module scope specifically so a node test can import them — `formatServerMetricsLine`, `buildPortableExportSnapshot`, `COMMAND_REGISTRY`

## Module Design

- `lcc_core` must stay importable **without FastAPI**. Anything needing a request object belongs in `lcc_api`
- One constant table should have one home. It currently doesn't: `CACHE_BYTES` exists in both `estimates.py` and `truth/kv.py` (the latter's comment admits it "mirrors" the former), and `CACHE_LADDER` lives in `smart_tune.py`. See CONCERNS
- Encoding: pass `encoding="utf-8"` explicitly to subprocess calls — node output broke the suite once without it
