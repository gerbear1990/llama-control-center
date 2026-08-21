---
description: "Operators can see whether a local model actually fits this machine before they launch it — and watch it once it runs."
type: Project
about: "llama-control-center"
---

# Llama Control Center

## What This Is

A local web dashboard for running LLMs on your own hardware. It discovers GGUF (and
related) model files, resolves them into launch profiles, estimates memory fit against
live hardware, and starts/stops tracked inference servers — llama.cpp, vLLM (incl. WSL),
and MLX. Once a server is up it proxies a test prompt, measures real tokens/sec, and
exposes the endpoint for downstream apps like OpenCode.

## Core Value

Operators can see whether a local model actually fits this machine *before* they launch
it — and keep watching it once it runs — instead of guessing at flags and reading OOM
tracebacks.

## Current State

| Attribute | Value |
|-----------|-------|
| Type | Application (FastAPI + vanilla-JS dashboard) |
| Version | 0.16.0 |
| Status | Production (single-operator, self-hosted) |
| Last Updated | 2026-08-21 |

**Run:** `python start-lcc.py start` → http://localhost:8716 (`lcc` shim at `~/bin/lcc.cmd`)
**Repo:** `gerbear1990/llama-control-center`

## Requirements

### Core Features

- Discover local models and resolve them into launch profiles
- Estimate memory fit (VRAM + RAM) against detected hardware, with green/orange/red verdicts
- Launch, track, and stop inference servers across llama.cpp / vLLM-WSL / MLX
- Observe running servers: metrics, process memory, crash detection, logs
- Smart-fit auto-tune and sampling suggestions derived from the estimator

### Validated (Shipped)

- [x] Fit estimation with RAM/VRAM bandwidth feeding tokens/sec — v0.6.0
- [x] Smart fit auto-tune + smart sampling suggestions — v0.6.3
- [x] Selected-model Hugging Face update check + targeted re-download — v0.6.2
- [x] Test-prompt box with measured tokens/sec — v0.9.0
- [x] Live server metrics, process memory, crash watchdog — **backend** v0.13.1
- [x] Live host hardware panel (`GET /api/system/live`) + OOM-likely annotation
- [x] KV-cache quant ladder incl. NVFP4/MXFP4 on accelerating NVIDIA GPUs — v0.13.1
- [x] Shell-code removal: no more .ps1/.sh generation or portable CLI — v0.16.0
- [x] Ground-truth memory layer derived from GGUF instead of tuned coefficients — merged `a1a6444`

### Active (In Progress)

- [ ] Terminal-instrument design pass — branch `feat/terminal-instrument-design`, uncommitted
- [ ] Embedded-MTP model support — paused at T7 of the models-pane plan; see issue #14

### Planned (Next)

- [ ] vLLM-WSL fit estimator + full auto-tuner
- [ ] Running-server observability UI (crash badge, metrics panel, log tail, rescan button)
- [ ] Frontend module split — `app.js` 3.8k lines, `styles.css` 4.1k lines
- [ ] Quant picker, Ollama integration, OpenCode provider auto-sync
- [ ] Obsidian Rail GUI overhaul (deliberately *after* the instrument-console IA pass)

## Constraints

- **Single source of truth for fit is the estimator** — every tuner and verdict reads it,
  so estimator changes ripple. Verify with a fit test or benchmark, never by eye.
- **No shell-script generation.** Removed in v0.16.0; `models.json` pins explicit
  `model_path`. Don't reintroduce launch-script codegen.
- Windows-first host, but hardware probes are per-OS (CIM / system_profiler / lspci) and
  must degrade gracefully rather than throw.
- Test suite needs UTF-8-aware decode for node subprocess output.
