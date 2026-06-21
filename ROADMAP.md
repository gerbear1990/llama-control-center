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

## Runtime Management

- Add a small apply-update button on runtime cards when an update is available.
  (Open: there is no safe universal updater — llama.cpp is typically built from
  source; the card currently links to the release page and offers a Recheck.)

## UI Polish

- Continue iterating on spacing, alignment, and visual hierarchy as new
  panels are added.
- Keep the style clean, modern, and utilitarian rather than decorative.
- Keep the style clean, modern, and utilitarian rather than decorative.

(Model Notes separation, the partial-state status tooltip, and the llama.cpp
live host/port preview are all shipped — see Completed.)

## Hugging Face Tooling

- Add a selected-model update check against Hugging Face.

(The HF CLI widget and draft-model suggestions/pulls are shipped — see Completed.)

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
