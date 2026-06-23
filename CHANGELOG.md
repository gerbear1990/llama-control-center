# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.10.4] - 2026-06-23

### Added

- **Runtime selection dropdown.** The Parameters panel now has a **Runtime**
  dropdown, populated from the detected environments and persisted per profile in
  `models.json`. llama.cpp is fully wired for Start/Fit; other detected runtimes
  (Ollama, LM Studio, vLLM, MLX) are selectable but yield a clear "not launchable
  yet" error from `prepare_launch_command` instead of silently falling back to
  llama.cpp. `detect_runtime()` dispatches a single runtime by id and rejects
  unknown ids. ([backends.py](lcc_core/backends.py),
  [server_manager.py](lcc_core/server_manager.py),
  [index.html](lcc_api/static/index.html), [app.js](lcc_api/static/app.js)) (#4)

## [0.10.3] - 2026-06-23

### Added

- **Context-size presets.** The Context field now has a themed preset picker
  (2K–256K) beside the input. It uses a native `<select>` (not a `<datalist>`),
  so it matches the app theme and always lists every preset regardless of the
  current value; the number input still accepts any custom value and remains the
  source of truth for Fit Test / Smart Fit. ([index.html](lcc_api/static/index.html),
  [app.js](lcc_api/static/app.js)) (#7)

### Fixed

- **Runtimes panel race.** The Runtimes panel could render "No runtimes detected"
  even when `/api/inventory` detected them, because the grid was only drawn by the
  `runtime-updates` resource — which, after v0.10.2's update-check caching, often
  resolved before the slower inventory scan. `renderRuntimes()` now also runs when
  inventory resolves, so the grid is order-independent. ([app.js](lcc_api/static/app.js)) (#5)
- **Smart Fit hang.** `auto_tune_fit()` re-parsed the GGUF header (~5s) for each of
  its ~144 partial-offload candidates, pinning a CPU core for ~11 minutes.
  `_read_gguf_n_layer()` is now memoized with `functools.lru_cache`, cutting a warm
  Smart Fit run from minutes to under a second. ([estimates.py](lcc_core/estimates.py)) (#6)

## [0.10.2] - 2026-06-23

### Changed

- **Quieter runtime cards.** Runtime cards no longer show a warning/error line
  (e.g. "unreachable") for runtimes that were not detected. An undetected runtime
  is an expected state, so the card simply shows `not found` without an error
  message. Warnings still appear for runtimes that *are* detected but have a
  problem (e.g. a reachable-but-erroring probe). ([app.js](lcc_api/static/app.js))

## [0.10.1] - 2026-06-23

### Changed

- **Shorter sampling labels.** The sampling-preset dropdown options are now single
  words (Coding, Factual, Balanced, Creative) so they no longer truncate; the full
  description remains as the option's hover tooltip. ([sampling.py](lcc_core/sampling.py))
- **Compact hardware chips.** The CPU and GPU header chips now show trimmed names
  (e.g. `Core i9-13900HK`, `Iris Xe Graphics`) instead of the raw vendor strings,
  wrap to two lines before truncating, and expose the full value on hover. The VRAM
  chip shows `Shared` for integrated GPUs instead of a dangling `-`.
  ([app.js](lcc_api/static/app.js), [styles.css](lcc_api/static/styles.css))

## [0.10.0] - 2026-06-23

### Added

- **Collapsible panels.** Every dashboard module now has a chevron toggle (and a
  clickable heading) that expands/collapses its body with a smooth
  `grid-template-rows` animation. Open/closed state persists per panel in
  `localStorage`. Secondary inspector panels (Test Prompt, Logs, Portability,
  HF Tools) start collapsed to reduce clutter. ([app.js](lcc_api/static/app.js),
  [styles.css](lcc_api/static/styles.css))
- **Collapsible sidebar.** A toggle button collapses the sidebar to an icon-only
  rail (with hover tooltips) and back, with an animated width transition; the
  state persists across reloads. ([index.html](lcc_api/static/index.html))

### Changed

- **Themed select controls.** All `<select>` elements (including the previously
  unstyled sampling-preset dropdown) now use `appearance: none` with a custom
  themed chevron, hover, and focus ring matching the rest of the inputs in both
  light and dark themes.
- Layout transitions are gated behind an `anim-ready` class applied after first
  paint, so panels and the sidebar never animate from open→closed on load.
  `prefers-reduced-motion` continues to disable all transitions.

## [0.9.0] - 2026-06-23

### Added

- **Test Prompt panel.** A new inspector panel sends a single chat message to the
  selected *running* tracked server via its `/v1/chat/completions` endpoint and
  shows the reply plus measured tokens/sec, completion token count, and elapsed
  time — without restarting the server or leaving the dashboard. Ctrl/Cmd+Enter
  sends. Backed by `send_chat_prompt()` ([benchmark.py](lcc_core/benchmark.py)) and
  the `POST /api/servers/test-prompt` endpoint ([app.py](lcc_api/app.py)). Closes the
  ROADMAP "test-prompt box" item.

## [0.8.1] - 2026-06-23

### Fixed

- **Linux CPU detection.** `detect_cpu()` had Windows and macOS branches but no
  Linux one, so it fell back to `platform.processor()` and reported the CPU as
  `x86_64` with an unknown core count — contradicting the README's "Detects CPU
  model" claim. It now reads the model name and physical core count from
  `/proc/cpuinfo` (stdlib only). ([hardware.py](lcc_core/hardware.py))

- **Linux GPU names.** `lspci`-detected GPUs dropped the
  `VGA compatible controller:` device-class prefix and the trailing `(rev NN)`
  so the header shows e.g. `Intel Corporation Raptor Lake-P [Iris Xe Graphics]`.
  ([hardware.py](lcc_core/hardware.py))

- **Fresh-clone test run.** The API smoke test now skips cleanly when
  `fastapi`/`httpx` are not installed instead of erroring the whole
  `unittest discover` run. ([test_lcc_api.py](tests/test_lcc_api.py))

### Changed

- The API version is now sourced from `lcc_api.__version__` instead of a
  duplicated literal, and a `test_version_strings_match` guard fails the suite
  if `pyproject.toml`, `lcc_api`, and `lcc_core` versions ever drift apart.

## [0.8.0] - 2026-06-22

### Added

- **Fresh clone works out of the box.** `find_project_root()` now recognizes
  `pyproject.toml` as a project root marker and falls back to the package location
  when no other marker is found walking up from cwd. An empty `models.json` ships with
  the repository so profiles can be created immediately after cloning.
  ([paths.py](lcc_core/paths.py), [models.json](models.json))

- **Fit test works on Apple Metal and other backends.** The memory-line parser in
  `parse_fit_output()` now matches all llama.cpp accelerator labels (`CUDA`, `MTL`,
  `METAL`, `ROCM`, `HIP`, `VULKAN`, `VK`, `SYCL`, `GPU`) instead of only CUDA.
  Parsed notes reflect the actual device name. ([fit.py](lcc_core/fit.py))

### Fixed

- **mmproj projector files no longer registered as launchable models.** The skip filter
  in `discover_models()` now matches `mmproj` anywhere in the filename (e.g.
  `gemma-4-default-mmproj.gguf`) instead of only at the start, bringing it in line with
  how draft/speculative companions are handled. ([models.py](lcc_core/models.py))

### Tests

- Added tests for Metal and ROCm memory-line parsing, mmproj-in-middle filename skipping,
  and package-location fallback for `find_project_root()`. ([test_lcc_core.py](tests/test_lcc_core.py))

## [0.7.1] - 2026-06-22

### Fixed

- **`stop-lcc.py` crashed on import.** It tried `from start_lcc import stop_server`,
  but the launcher file is `start-lcc.py` — a hyphen is not a legal module name, so the
  import always failed with `ModuleNotFoundError`. It now loads `start-lcc.py` by path via
  `importlib` and reuses its `stop_server()`. ([stop-lcc.py](stop-lcc.py))
- **`status` printed a malformed dashboard URL** (`http://<pid>`). It now prints the
  correct `http://<host>:<port>/` using shared `DEFAULT_HOST` / `DEFAULT_PORT` constants,
  which also replace the magic port numbers in the argparse defaults and port fallback.
  ([start-lcc.py](start-lcc.py))

## [0.7.0] - 2026-06-22

### Added

- **Auto-generated launch scripts.** A new module scans the configured model folders
  and generates a portable PowerShell launch script for every discovered model, written
  into the project's `scripts/` folder so the existing manifest parser picks them up. A
  POSIX `.sh` companion is generated on non-Windows hosts. The scan runs automatically at
  API startup (gated by the `auto_scan_on_startup` / `auto_generate_launch_scripts`
  config flags) and is exposed via `GET /api/launch-scripts`, `POST /api/launch-scripts/scan`,
  `POST /api/launch-scripts/generate`, and `POST /api/launch-scripts/delete`.
  ([launch_scripts.py](lcc_core/launch_scripts.py), [app.py](lcc_api/app.py))
- **New models become launchable profiles.** Models discovered on disk with no
  `models.json` entry are registered as new profiles (with autotuned starter parameters)
  so they appear in the dashboard immediately.
- **Broken script references repaired.** When a profile's referenced launch script is
  missing, the scan repoints it at the generated script, letting resolution pin an exact
  model path (confidence 1.0) instead of falling back to fuzzy name matching.

### Changed

- Generated scripts are written to `<project_root>/scripts/`; `list_launch_scripts` is
  state-driven so co-located hand-written scripts (e.g. `switch-model.ps1`) are never
  reported or overwritten.
- The FastAPI startup autoscan hook was migrated from the deprecated `@app.on_event`
  to a `lifespan` context manager.

### Fixed

- Speculative/draft companion models (e.g. `*-MTP` files) are no longer handed a
  standalone server script.
- The `.sh` companion is skipped on Windows, where its drive-letter-absolute paths could
  never run.
- Test isolation: the launch-scripts test suite now sandboxes the working directory so a
  startup-autoscan path can never touch a real `models.json`.

## [0.6.3] - 2026-06-21

### Added

- **Smart fit auto-tune.** A "Smart fit" button searches the launch-parameter space
  (GPU layers → context size → KV cache type) against the memory estimator and applies
  the configuration with the highest safe utilization — max GPU offload first, then the
  largest context that fits, then the highest-fidelity KV cache. Rejects any candidate
  the estimator flags as near-limit or can't size against real VRAM, and shows a
  before/after fit + speed summary with per-change rationale.
  ([smart_tune.py](lcc_core/smart_tune.py), [app.py](lcc_api/app.py),
  [app.js](lcc_api/static/app.js))
- **Smart sampling suggestions.** A sampling-preset selector ("Suggest sampling")
  fills temperature, top-k, top-p, min-p, and repeat penalty from a chosen task intent
  (coding / factual / balanced / creative), each with a one-line rationale. Presets are
  starting points, applied to the profile's sampling fields.
  ([sampling.py](lcc_core/sampling.py), [app.py](lcc_api/app.py),
  [app.js](lcc_api/static/app.js))

## [0.6.2] - 2026-06-21

### Added

- **Selected-model Hugging Face update check + targeted re-download.** An "HF update"
  button on the model panel resolves the selected profile's model to its HF repo and
  compares the remote file against the local copy (size diff is the primary signal;
  repo last-modified is a low-confidence fallback). When a newer copy exists and the
  exact remote file is known, a confirm-gated "Download latest" button re-pulls just
  that file into the model's own directory via `huggingface-cli`. Search-matched repos
  are flagged as needing verification before download.
  ([app.js](lcc_api/static/app.js), [app.py](lcc_api/app.py),
  [hf_metadata.py](lcc_core/hf_metadata.py), [draft_models.py](lcc_core/draft_models.py))

## [0.6.1] - 2026-06-21

### Added

- **Per-runtime "Recheck" button** on each runtime card. It bypasses the update
  cache for just that one runtime (one GitHub call) while the others continue to
  serve from cache. ([app.js](lcc_api/static/app.js),
  [app.py](lcc_api/app.py), [runtime_updates.py](lcc_core/runtime_updates.py))

### Changed

- **Model Notes panel keeps HF info, fit-test, and benchmark results in separate
  titled blocks** instead of overwriting one another, so running a benchmark no
  longer wipes the fit recommendation. ([app.js](lcc_api/static/app.js),
  [styles.css](lcc_api/static/styles.css))

### Docs

- Synced `ROADMAP.md` and `TODO.md` to reality — most listed items (runtime update
  checks, update channel, HF CLI widget, draft models, RAM/VRAM bandwidth, live
  host/port preview, profile Stop button) were already shipped but still marked open.

## [0.6.0] - 2026-06-21

### Fixed

- **Server stop is now reliable.** `stop_server` escalates to `SIGKILL` on POSIX
  when a server ignores `SIGTERM`, so the Stop button can't be defeated by a hung
  process. `pid_is_running` now treats unreaped zombie children (Linux `/proc`) as
  dead, so a stopped server no longer lingers as "running", and a tracked entry with
  no PID stops cleanly instead of raising. ([server_manager.py](lcc_core/server_manager.py))

- **Started servers survive control-center shutdown.** `start_profile` launches with
  `start_new_session=True` so a terminal/process-group signal (Ctrl-C, `systemd stop`)
  to the app no longer takes down the inference servers it tracks.
  ([server_manager.py](lcc_core/server_manager.py))

- **Tokens/sec estimate honors memory bandwidth as a ceiling.** Detected VRAM/RAM
  bandwidth now caps decode speed (a token can't be produced faster than its weights
  stream) instead of being used as a speed boost, and "high" confidence is reported
  only when that cap actually binds. Fixed bits→bytes (`/8`) errors in the GPU, RAM-
  spill, and VRAM-bandwidth math, and added an `F32` quant case.
  ([estimates.py](lcc_core/estimates.py), [hardware.py](lcc_core/hardware.py))

- **GPU layer arguments are normalized consistently.** A shared `normalize_gpu_layers`
  helper accepts `all`/`auto`/`max` and float-ish strings everywhere launch args are
  built, removing inconsistent ad-hoc coercion. ([llama_args.py](lcc_core/llama_args.py))

- **Save Profile no longer has divergent create/update paths** that could silently fail
  to persist; both paths now share one atomic write. ([app.py](lcc_api/app.py))

### Changed

- **Dashboard startup and refresh are parallel and progressive.** The eight dashboard
  endpoints are now fetched concurrently and each section paints as its own data
  arrives, instead of awaiting all eight sequentially behind the slow GitHub-backed
  runtime-update check. Refresh re-renders only the section whose data changed rather
  than rebuilding the entire UI. ([app.js](lcc_api/static/app.js))

### Removed

- Dead full-rebuild functions (`renderAll`, `refreshUI`) and a duplicate
  `detect_hf_cli` in `draft_models.py`; deduplicated path-key logic in `paths.py` and
  cleaned up unused imports. Dropped unused `streamlit`, `urllib3`, and `pandas` from
  `requirements.txt` (added `pydantic`). ([app.js](lcc_api/static/app.js),
  [draft_models.py](lcc_core/draft_models.py), [paths.py](lcc_core/paths.py),
  [requirements.txt](requirements.txt))

## [0.5.0] - 2026-06-21

### Fixed

- **GPU/VRAM detection on Windows** — Fixed `PNPDeviceID` parsing in the Windows CIM
  fallback. The previous code split `DeviceID` (e.g. `VideoController2`) instead of
  `PNPDeviceID` and expected a `PCI\AAAA\BBBB` layout. VRAM bus width, data rate, and
  bandwidth are now correctly extracted via regex on `PNPDeviceID` (`VEN_`, `DEV_`,
  `REV_` tokens). ([hardware.py](lcc_core/hardware.py))

- **nvidia-smi query fields** — The query previously asked for `memory.bus_width` and
  `memory.data_rate`, which are not valid `nvidia-smi` fields. This caused the entire
  nvidia-smi GPU detection path to fail silently. The query now uses `clocks.current.memory`
  and `clocks.max.memory` for bandwidth data, and a new
  `_nvidia_bus_width_from_name()` function infers bus width from the GPU product name.
  ([hardware.py](lcc_core/hardware.py))

- **Missing GPU device IDs** — Added support for many newer GPUs that were absent from
  the lookup tables:
  - NVIDIA RTX 50-series (Blackwell): 5090, 5080, 5070 Ti, 5070, 5060
  - NVIDIA RTX 40-series: 4070 Ti Super, 4070 Super, 4060 Ti 16 GB
  - NVIDIA RTX 30/20-series, GTX 16/10-series, Tesla/A/L-series, Quadro
  - AMD RX 9000/8000/7000/6000 series (RDNA 4 / RDNA 3 / RDNA 2)
  ([hardware.py](lcc_core/hardware.py))

- **Memory fit accuracy** — The layer fraction calculation previously used a hardcoded
  divisor of 80 layers, which produced incorrect VRAM/RAM estimates for models with
  different layer counts (e.g. Gemma with 60 layers, Mistral with 40). The
  `_layer_fraction()` function now reads the actual layer count from the GGUF file
  metadata (`<arch>.block_count` / `<arch>.n_layer`) via the `gguf` Python package,
  falling back to tensor name scanning. ([estimates.py](lcc_core/estimates.py))

### Added

- `gguf>=0.19.0` added to `requirements.txt` for GGUF metadata parsing.
  ([requirements.txt](requirements.txt))

## [0.4.2] - 2026-06-20

### Fixed

- Hugging Face CLI actual install and update check against PyPI.
- Custom rename and save profile dialogs with proper modal handling.

## [0.4.1] - 2026-06-19

### Fixed

- Refresh button, prepare/stop logic.
- Profile naming, grouping, and persistence.
- HF install button and draft model queries.
- Stop button for running servers.

## [0.4.0] - 2026-06-17

### Added

- Draft model suggestions for speculative decoding with one-click pull.
- Hugging Face CLI widget with detect/install/update.
- Server management scripts (`start-lcc.py`, `stop-lcc.py`).
- RAM/VRAM bandwidth detection and improved TPS confidence.
- Profile grouping by matched model with collapsible headers.
- Profile rename and save dialogs.
- Server history limit configuration.

## [0.3.0] - 2025-01-XX

### Added

- Fit tests with `llama-fit-params`.
- Benchmark button for measured tokens/sec.
- Port forwarding, firewall rules, and network management.

## [0.2.0]

Initial public release with core dashboard features.

## [0.1.0] - 0.1.2

Early development releases.
