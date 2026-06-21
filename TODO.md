# Llama Control Center TODO

## Current Feature Pass

- [x] CUDA estimate automatically updates when settings are manually changed.
- [x] Full support for non-CUDA GPUs, including AMD, Intel discrete GPUs, and integrated GPUs.
- [x] Metal acceleration options when macOS is detected.
- [x] MLX runtime support.
- [x] Show fit status per profile using VRAM and RAM-aware estimates:
  - Good: green
  - Tight: orange
  - Near Limit: red
- [x] Include RAM in fit status when CPU/offload settings need host memory.
- [x] Show the CPU model in the header, not just core count.
- [x] Add a full benchmark option using the current selected parameters.
- [x] Store and display precise benchmark tokens/sec and other useful runtime measurements.
- [x] Commit finished work to `gerbear1990/llama-control-center`.
- [x] Generate a repository README with setup and run instructions.

## Roadmap Candidates

- [x] Runtime cards should show binary location, API URL, and active port.
- [x] Runtime cards should check for runtime updates automatically.
- [x] Settings should let users choose stable releases or another update channel.
- [x] Per-runtime "Recheck" button on each runtime card (rechecks just that runtime). _v0.6.0._ Apply-update action is still out of scope (no safe universal updater; building llama.cpp from source is platform-specific).
- [x] Run a full UI pass for spacing, responsive layout, visual polish, and modern clean styling.
- [x] Draft model field should suggest compatible draft models for the selected profile.
- [x] Draft model workflow should optionally pull compatible draft models from Hugging Face.
- [x] Detect whether the Hugging Face CLI is installed and use it for pulls when available.
- [x] Add a main-page Hugging Face CLI widget (install when missing, detected version, update check, apply update).
- [x] Estimated speed should aim for high confidence when enough hardware/model data exists, then fall back to medium or low. _v0.6.0._
- [x] RAM detection should include DDR generation, speed, and estimated bandwidth where the OS exposes it.
- [x] VRAM detection should include memory generation, speed, and bandwidth where the GPU tooling exposes it.
- [x] RAM/VRAM speed and bandwidth should feed into tokens/sec estimates and fit scoring when useful. _v0.6.0 (bandwidth applied as a decode ceiling)._
- [x] Add a button to check Hugging Face for updates to the selected model. _v0.6.2 — resolves the model's HF repo, compares remote vs local file (size diff primary, repo last-modified fallback), and offers a confirm-gated re-download of just that file._
- [ ] Add full Ollama support so users can use Ollama as a preferred model/runtime source instead of Hugging Face.
- [x] Refine and tighten the Model Notes panel after a benchmark runs so the result is laid out cleanly and clearly separated from the fit-test output. _v0.6.0 (HF / fit / benchmark each in their own titled block)._
- [x] Verify and harden stop-server logic so a tracked server actually transitions from running to stopped after Stop is clicked, with the dashboard reflecting the new state.
- [x] After a benchmark completes, force the live "Estimated speed" card to show the benchmarked tokens/sec for the current profile instead of the heuristic estimate.
- [ ] Tighten the tokens-per-second estimation logic so it tracks real measured performance more closely across model sizes, quantizations, and runtimes. _Partly addressed in v0.6.0 (bandwidth ceiling + unit fixes); full calibration against real benchmarks is ongoing._
- [x] Investigate whether a script can register locally tracked llama.cpp servers with downstream apps such as OpenCode, so the running server appears as a usable model provider without manual configuration.
- [ ] Auto-sync LCC's tracked server state with the OpenCode provider config so a new profile mode does not need a manual JSONC edit before OpenCode can address it.
- [x] When the API status indicator shows a partial state, surface a hover tooltip listing which endpoints succeeded and which failed (and why).
- [x] Profiles table should show a Stop button for profiles with a running server, wired to the same stop logic as the Servers panel.
- [x] Runtimes panel should show the live preview host/port from the Parameters panel for llama.cpp, letting users see what endpoint their current settings would use.
- [x] Fit test should pass all user-configurable parameters to llama-fit-params so the output includes fitted values for the complete parameter set.
- [x] Check for updates button should give clear feedback when no runtimes support update checks (no version detected, unsupported runtime).
