# Roadmap

This roadmap collects candidate features before they are designed and scheduled.
Items here are not release promises; they are the working direction for the next
passes.

## Completed

- Runtime cards show each runtime's binary/module location, API or probe URL,
  and port. Added in `v0.1.1`.
- Full UI pass over spacing, responsive behavior, visual hierarchy, modal
  patterns, focus management, color contrast, and version surface. Added in
  `v0.1.2`.
- Manual OpenCode CLI/Desktop wiring for LCC-spun llama.cpp servers: added
  `lcc_default_port` and `lcc_alt_port` providers (ports 8080 and 8081) to
  `~/.config/opencode/opencode.jsonc` with model IDs that match the
  `--alias {profile.mode}` convention LCC uses when launching. OpenCode
  Desktop reads the same JSONC, so both clients are covered. Verified with
  a live `chat.completions` call against the running Qwen3.6 server.
- API status hover tooltip: when the API shows a partial state, hovering
  the status dot shows which endpoints succeeded/failed with error details.
  Added a copy-to-clipboard button for error diagnostics. Added in `v0.3.0`.
- Stop-server logic hardened: after sending a kill signal, the server manager
  polls to verify the process actually exited within 5 seconds before marking
  the server as stopped. Added in `v0.3.0`.
- Benchmark measured TPS: after a benchmark completes, the speed estimate
  card shows the measured tokens/sec (with "(measured)" suffix) instead of
  the heuristic estimate, persisting until parameters change. Added in
  `v0.3.0`.
- Runtime update checks: automatic on load plus a manual "Check for updates"
  button, an update channel selector (stable/prerelease) in Settings, update
  badges on runtime cards, and clear feedback when no runtime supports checks
  (no version detected / not tracked). Added in `v0.5.x`.
- Draft model suggestions, HF pulls, and the Hugging Face CLI widget
  (detect/version/update/install). Added in `v0.4.x`.
- RAM/VRAM DDR generation, speed, and bandwidth detection feeding into
  tokens/sec estimates. Added in `v0.4.x`–`v0.6.0`.
- Reliable server lifecycle: SIGKILL escalation when SIGTERM is ignored,
  zombie detection, and detached (`start_new_session`) servers that survive
  control-center shutdown. Speed estimates now treat detected memory bandwidth
  as a decode ceiling with confidence gated on it. Added in `v0.6.0`.
- Per-runtime "Recheck" button on each runtime card, and a Model Notes panel
  that keeps HF info, fit-test, and benchmark results in separate titled
  blocks. Added in `v0.6.0`.
- Selected-model Hugging Face update check: resolves the model's HF repo,
  compares the remote file against the local copy (size diff primary, repo
  last-modified fallback), and offers a confirm-gated re-download of just that
  file into the model's directory. Added in `v0.6.2`.
- Smart fit auto-tune: greedy search over the memory estimator (GPU layers →
  context → KV cache type) that applies the highest safe-utilization config with a
  before/after fit + speed summary and per-change rationale. Rejects near-limit and
  unsized-VRAM candidates. Added in `v0.6.3`. (Ceiling: only as accurate as the
  estimator; verify with a fit test or benchmark.)
- Smart sampling suggestions: task-intent presets (coding / factual / balanced /
  creative) for temperature, top-k, top-p, min-p, and repeat penalty, each with a
  one-line rationale, applied to the profile's sampling fields. Added in
  `v0.6.3`. (Ceiling: convention presets, not learned per-model optima.)

## Running Server Tooling

The dashboard is strong pre-launch (discover → fit → estimate → prepare → start)
but goes quiet once a server is running. These close that loop.

> Detailed breakdown of remaining UI work (plus many other review items) lives in  
> **[REVIEW_MILESTONES.md](./REVIEW_MILESTONES.md)** — see especially **M2: Running Server Observability**.

_The backend for live metrics and the crash watchdog is shipped (`v0.13.1`):
`GET /api/servers/{id}/metrics` polls `/metrics`/`/health`/`/props`, and
`refresh_server_states` flags unexpectedly-dead tracked servers as `crashed`
with a stderr snapshot. The UI panels that surface these are still pending._

- ~~Test-prompt box against a running server~~ **Shipped in `v0.9.0`.** Test Prompt
  panel proxies to the running server's `/v1/chat/completions` and shows the reply
  plus measured tokens/sec.
- Live server metrics from llama.cpp: poll the running server's `/metrics`
  (Prometheus), `/health`, and `/props` for real KV-cache usage, slots in use,
  prompt/decode tokens/sec, and context fill %. Turns the estimate into ground truth
  and feeds the ongoing TPS calibration. **Backend shipped `v0.13.1`; UI pending.**
- Live process memory gauge: show the tracked PID's actual resident memory (and GPU
  memory via existing tooling) while it runs, to confirm the pre-launch fit estimate
  and catch surprise OOMs. **Shipped (Unreleased).** `GET /api/servers/{id}/metrics`
  now returns a `process` block with `rss_bytes` (psutil, portable) and `gpu_used_bytes`
  (NVIDIA-only, via shared `nvidia-smi --query-compute-apps`).
- Crash/exit watchdog: surface when a tracked server has died unexpectedly (badge it
  "crashed", show last log lines, offer restart) instead of showing stale running state.
  **Detection shipped `v0.13.1`; UI surfacing pending.**
- Log tail panel: capture detached server stdout/stderr to a file and tail it in the
  UI, so debugging a bad launch doesn't mean leaving the app. _(Server stdout/stderr
  paths are already captured per tracked server; a dedicated tail panel is pending.)_

## Quant Selection

- Quant picker for a repo: combine the repo file-tree listing (from the HF update
  check) with `fit.py` to show every available quant with its size and a
  green/orange/red fit verdict, so the user picks the largest quant that fits at a
  glance.

## Smart Fit

- ~~Expand the KV-cache quant ladder beyond `f16 / q8_0 / q5_1 / q4_0`.~~ **Shipped
  `v0.13.1`.** The memory estimator (`estimates.py`) already prices `q5_0`,
  `q4_1`, and `iq4_nl`, so they're now search rungs — for both K and V, which are
  tuned independently — giving the asymmetric search finer memory/quality landing
  spots. The 4-bit float formats **NVFP4** and **MXFP4** are also priced (exact
  llama.cpp block ratios) and added as rungs on NVIDIA CUDA GPUs that
  hardware-accelerate them (Blackwell/Hopper/Ada/A100/L4-L40), preferred over
  integer `q4_0` at the same byte rate.

## Runtime Management

- Add a small apply-update button on runtime cards when an update is available.
  (Open: there is no safe universal updater — llama.cpp is typically built from
  source; the card currently links to the release page and offers a Recheck.)

## UI Polish

- Continue iterating on spacing, alignment, and visual hierarchy as new
  panels are added.
- Keep the style clean, modern, and utilitarian rather than decorative.

(Model Notes separation, the partial-state status tooltip, and the llama.cpp
live host/port preview are all shipped — see Completed.)

## Live Host Hardware

The full SwarmUI hardware-monitoring pattern ported to Python: a live
`nvidia-smi` poll for GPU utilization / temperature / VRAM, a system-RAM
read, and a short rolling RAM window that lets the crash watchdog annotate
freshly-crashed servers with an `oom_likely` flag when memory was already
under pressure before the death.

- ~~Live host hardware panel~~ **Shipped (Unreleased).** `GET /api/system/live`
  returns `{system_ram:{total,used,free}, gpus:[{util, temp, total/free/used_vram}], source, cached_age_ms}`,
  TTL-cached (2s) behind a lock + one-shot graceful disable (SwarmUI's
  `NvidiaQueryRateLimitMS` + `HasNvidiaGPU` pattern). A matching `#live-hardware`
  dashboard panel polls every 3s (paused when the tab is hidden or the panel is
  collapsed) and renders GPU util/temp/VRAM bars + a system-RAM bar with
  green/amber/red thresholds.
- ~~Crash watchdog OOM hint~~ **Shipped (Unreleased).** `refresh_server_states()`
  appends each refresh's RAM pressure to a 10-sample rolling window and
  annotates freshly-crashed servers with `oom_likely: true` when the peak
  exceeded 80% (mirrors SwarmUI's `NetworkBackendUtils` pre-crash
  memory-overload heuristic).
- Per-process memory gauge: **Shipped (Unreleased)** — see "Running Server
  Tooling" above for the server_metrics endpoint details.

## Hugging Face Tooling

(The HF CLI widget, draft-model suggestions/pulls, and the selected-model update
check + targeted re-download are all shipped — see Completed.)

## Estimates And Hardware Detail

- Tighten the tokens-per-second estimation logic so it tracks real
  measured performance more closely across model sizes, quantizations,
  and runtimes. `v0.6.0` added a memory-bandwidth ceiling and fixed the unit
  math; full calibration against real benchmarks is still ongoing.

(High/medium/low confidence gating, RAM/VRAM bandwidth detection feeding the
estimate, measured-TPS pinning, and full-parameter fit tests are shipped — see
Completed.)

## Downstream Integration

- Auto-sync LCC's tracked server state with the OpenCode provider config:
  on Start, register an OpenCode provider (or refresh the model IDs) for
  the chosen host/port and `--alias`; on Stop, retire it. Avoid the
  current limitation where new profile modes need a manual JSONC edit
  before OpenCode can address them.

## Ollama

- Add full Ollama integration.
- Let users choose Ollama as their preferred source/runtime flow instead of
  Hugging Face where appropriate.
- Support Ollama model discovery, launch/status display, model pulls, and
  update flows in the same dashboard language as local GGUF profiles.
