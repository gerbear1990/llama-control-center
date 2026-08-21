# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary audience: local-LLM operators — people who sit at their own Windows, Linux, or macOS machine with GGUF (and related) files, a detected runtime, and real hardware limits.

Job when they open the dashboard: pick a profile, see whether it fits this machine, start a tracked local server, then talk to it or hand the endpoint to another app.

The product is for operators like the author, not a single private install and not a downstream-app-only control plane.

## Product Purpose

Llama Control Center is a local dashboard for discovering models, resolving launch profiles, estimating memory fit against live hardware, and starting or stopping tracked inference servers.

Success is a server that is actually listening on the intended host and port without an avoidable OOM, with the operator able to see why a fit is good, tight, near the limit, or held on CPU.

Chat is a probe of a running server, not the product.

## Positioning

Hardware-honest local launch. A neighboring chat studio or model catalog cannot truthfully claim this combination: live host/GPU facts, VRAM/RAM-aware fit language, `models.json` profiles pinned to an explicit model path, and Start/Stop that only manage servers this app tracked.

## Operating Context

Operators run the dashboard as a local web app at `http://127.0.0.1:8716/` via `python start-lcc.py` / `python stop-lcc.py` (or `python -m lcc_api`).

Typical loop: configure scan/runtime roots in Settings → inventory discovers GGUF and runtimes → register or select a profile → edit launch parameters → Smart Fit or Fit test → Start → copy the listening URL or open Chat → Stop when done.

`models.json` is the on-disk profile manifest. Scan roots and runtime roots are the portability levers; paths belong in settings or environment, not in source.

Started servers are detached so they outlive the control center. The dashboard talks to a FastAPI backend that must not be started from an agent session: startup autoscan can rewrite `models.json`.

A later visual overhaul on Obsidian Rail is parked in `TODO.md` and is out of scope until the user unparks it.

## Capabilities and Constraints

Confirmed:

- Vanilla HTML, CSS, and JavaScript in `lcc_api/static/`. One token system. Do not introduce third-party design-system names.
- Destinations: Console (Stage, Chat, Logs, Server), Inventory, Tools.
- llama.cpp is the fully wired launch path. Other runtimes (Ollama, LM Studio, vLLM, MLX, WSL llama.cpp) are detected; vLLM-in-WSL exists for supported NVFP4/safetensors profiles.
- Fit statuses: Good, Tight, Near Limit, unknown. Smart Fit searches the estimator grid; it must not treat Tight as Good, must size against total VRAM, and must show notes / CPU fallback before applying.
- Profiles pin `model_path`. Matcher/registration is the source of truth for old vs new models, not empty-state copy.
- Never git-stage `models.json`.
- Never start the LCC API from an agent context.

Undecided (do not invent):

- Whether Start of an already-launchable profile should skip the confirm dialog.
- When, if ever, to apply the parked Obsidian Rail visual overhaul.

## Brand Commitments

Name: Llama Control Center (LCC). Sidebar mark: LC. Existing product line: “Portable local LLM ops.”

Voice is operator-facing and machine-honest: name the endpoint, the PID, the fit, the failure, and the recovery. Do not add generic whimsy, mascots, or celebration for ordinary clicks.

## Evidence on Hand

Runnable dashboard and API in this repo (`lcc_api/`, `lcc_core/`, `lcc_api/static/`). Real hardware detection, real `models.json` on the operator’s machine, real tracked-server logs.

Do not fabricate testimonials, customer counts, benchmark leaderboards, pricing, or “works on every GPU” claims. Speed cards are estimates unless a benchmark on this profile produced a measured tok/s.

## Product Principles

1. Fit before launch: the operator should know whether this machine can hold the model before Start.
2. Pin what you mean: a profile is a path and a launch config, not a fuzzy name match.
3. Track only what you started: Start/Stop/Logs describe this app’s servers, not every process on the box.
4. Portability is configuration, not hardcoded user paths.
5. Chat verifies a listener; it does not replace the launch instrument.
