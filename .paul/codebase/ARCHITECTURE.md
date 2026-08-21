---
description: "Llama Control Center — architecture"
type: CodebaseDoc
about: "llama-control-center"
---

# Architecture

## Pattern Overview

A **two-layer local application**: a portable, UI-agnostic core (`lcc_core/`) wrapped by a thin
FastAPI transport layer (`lcc_api/`) that also serves a static dashboard. The core holds all
domain logic and knows nothing about HTTP; the API layer is mostly parse → call core → return dict.

The defining idea is a **single estimator that everything reads**. Fit verdicts, the smart-fit
auto-tuner, and the launch preview all derive from the same memory arithmetic, so a change there
ripples through every surface at once.

## Layers

**1. Truth layer — `lcc_core/truth/`** (newest, merged `a1a6444`)
Ground-truth facts read from the artifact itself rather than tuned coefficients.
- `truth/gguf.py` — "Typed architecture facts read from a GGUF header"
- `truth/kv.py` — "Memory arithmetic over ArchFacts. **Pure: no I/O, no globals, no clock.**"
- `truth/shadow.py` — runs the truth layer beside the legacy estimator and logs disagreement

**2. Domain core — `lcc_core/`**
- *Discovery/identity:* `models.py`, `inventory.py`, `manifest.py`, `paths.py`, `schema.py`
- *Profiles:* `profile_registry.py` (register discovered models into `models.json`), `profile_resolver.py` (manifest + scan → launchable profile)
- *Memory + fit:* `estimates.py` (1,019), `fit.py`, `smart_tune.py` (greedy search over the estimator)
- *Hardware:* `hardware.py` (999) — per-OS probes
- *Launch args:* `llama_args.py`, `vllm_args.py`, `sampling.py`, `draft_models.py`
- *Process lifecycle:* `server_manager.py` (1,172) — tracked state, port/pid detection, launch orchestration, WSL/vLLM stop, crash watchdog
- *Runtime observation:* `server_metrics.py`, `benchmark.py`
- *External lookups:* `hf_metadata.py`, `hf_cli.py`, `runtime_updates.py`

**3. Transport — `lcc_api/app.py`** (745 lines, 41 routes)
FastAPI app with a `lifespan` that runs profile registration at startup. 13 Pydantic request models declared in the same file.

**4. Presentation — `lcc_api/static/`**
`app.js` (5,060) + `styles.css` (4,156) + `index.html` (733). No build step.

## Data Flow

**Pre-launch (the strong path):**
```
model files on disk
  → discover_models()            models.py / inventory.py
  → resolve_profiles()           profile_resolver.py  (+ manifest.py reads models.json)
  → GGUF header facts            truth/gguf.py → ArchFacts
  → memory arithmetic            truth/kv.py + estimates.py
  → fit verdict green/orange/red fit.py
  → optional greedy auto-tune    smart_tune.py  (gpu-layers → context → KV cache type)
  → launch args                  llama_args.py / vllm_args.py
  → spawn + track                server_manager.py  (detached, start_new_session)
```

**Post-launch (backend complete, UI thin):**
```
tracked server
  → /metrics /health /props poll   server_metrics.py
  → psutil RSS + nvidia-smi        process block
  → refresh_server_states()        crash detection + oom_likely from a 10-sample RAM window
  → GET /api/servers/{id}/metrics  ← the servers panel renders ONE line of this payload
```

## Key Abstractions

| Abstraction | Lives in | Role |
|---|---|---|
| `ArchFacts` | `truth/gguf.py` | typed model architecture read from the GGUF header |
| Profile | `profile_resolver.py`, `models.json` | a launchable configuration: model path, mode/alias, params |
| Tracked server | `server_manager.py` | a spawned process with persisted state, pid, port, log paths |
| Fit verdict | `fit.py` | green / orange / near-limit against live VRAM+RAM |
| Cache ladder | `estimates.py`, `smart_tune.py` | ordered KV quant rungs the tuner searches |

## Entry Points

- `start-lcc.py` (343 lines) — the operator entry point; `python start-lcc.py start` → :8716. `lcc` shim at `~/bin/lcc.cmd`
- `stop-lcc.py`
- `lcc_api/__main__.py` — `python -m lcc_api`
- `lcc_api/app.py:app` — the ASGI app; `lifespan` triggers startup profile registration
- `GET /` — serves `index.html`

## Error Handling

API layer converts domain failures to `HTTPException` — 20 raises in `app.py`, **17 of them `400`** and 2 `404`. This flatness is a known gap: audit item M1.4 wants real categories (port conflict, OOM-likely, missing binary) instead of a generic 400.

Hardware and runtime probes are **best-effort by design** — `runtime_updates.py` is documented as "best-effort ... against public release sources", and the `/api/system/live` NVIDIA path has a one-shot graceful disable so a missing `nvidia-smi` degrades instead of throwing.

## Cross-Cutting Concerns

- **TTL + lock caching** — `/api/system/live` uses a 2s lock+TTL. The audit proposes reusing this pattern for `/api/profiles`, which currently recomputes manifest + scan + GGUF metadata + fit on every call.
- **GGUF metadata cache** keyed on `(size, mtime)`; the paused plan bumps it to v4 to carry an `mtp` flag.
- **Detached processes** — servers spawn with `start_new_session` so they survive the control center exiting.
- **Shadow mode** — `truth/shadow.py` lets the new memory layer run beside the old one and log divergence rather than replacing it outright.
