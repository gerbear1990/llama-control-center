# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
