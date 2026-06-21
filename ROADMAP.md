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

## Runtime Management

- Add automatic runtime update checks.
- Let users choose an update channel in settings, such as stable or another
  release stream when the runtime supports it.
- Check for updates gives clear feedback when no runtimes support update
  checks (no version detected, unsupported runtime) instead of failing
  silently or with cryptic errors. Ollama version detection added.
- Add a small apply-update button on runtime cards when an update is available.
- Verify and harden stop-server logic so a tracked server actually
  transitions from running to stopped after Stop is clicked, with the
  dashboard reflecting the new state. **Completed in `v0.3.0`** with
  post-kill polling to verify process exit.
- Profiles table now shows a Stop button for profiles with a running
  server, wired to the same stop logic as the Servers panel.

## UI Polish

- Continue iterating on spacing, alignment, and visual hierarchy as new
  panels are added.
- Keep the style clean, modern, and utilitarian rather than decorative.
- Refine the Model Notes panel after a benchmark runs so the result is
  laid out cleanly and clearly separated from the fit-test output.
- When the API status indicator shows a partial state, surface a hover
  tooltip listing which endpoints succeeded and which failed (and why).
  **Completed in `v0.3.0`** with a copy-to-clipboard button.
- Runtimes panel shows a live preview of the host/port from the Parameters
  panel for llama.cpp, letting users see what endpoint their current
  settings would use without starting a server.

## Draft Models

- Suggest compatible draft models for the selected profile and base model.
- Offer optional Hugging Face pulls for compatible draft models.
- Detect the Hugging Face CLI and use it when available for model downloads.

## Hugging Face Tooling

- Add a main-page Hugging Face CLI widget that can:
  - detect whether the CLI is installed,
  - show the installed version,
  - offer install guidance or an install action when missing,
  - check for CLI updates,
  - apply a CLI update when the user chooses it.
- Add a selected-model update check against Hugging Face.

## Estimates And Hardware Detail

- Push speed estimates toward high confidence when model metadata, runtime
  backend, GPU, VRAM, RAM, and benchmark calibration data are available.
- Fall back clearly to medium or low confidence when inputs are incomplete.
- Detect RAM DDR generation, speed, and estimated bandwidth where available.
- Detect VRAM memory generation, speed, and estimated bandwidth where available.
- Feed RAM and VRAM speed/bandwidth into tokens/sec estimates and fit scoring
  when the signal is reliable enough to help.
- Tighten the tokens-per-second estimation logic so it tracks real
  measured performance more closely across model sizes, quantizations,
  and runtimes. The current heuristic can drift wildly from real
  benchmarks and must be recalibrated.
- After a benchmark completes for a profile, let the user pin the
  measured tokens/sec over the heuristic estimate on the live
  Estimated Speed card. **Completed in `v0.3.0`** - measured TPS is
  shown automatically after benchmark and persists until parameters
  change.
- Fit test now passes all user-configurable parameters to llama-fit-params
  (temperature, top_k, top_p, min_p, penalties, seed, n_predict, reasoning)
  so the fitted output covers the complete parameter set.

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
