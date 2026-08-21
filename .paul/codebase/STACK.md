---
description: "Llama Control Center — technology stack"
type: CodebaseDoc
about: "llama-control-center"
---

# Technology Stack

## Languages

| Language | Where | Notes |
|---|---|---|
| Python 3.10+ | `lcc_api/`, `lcc_core/`, `tests/`, `start-lcc.py` | 46 tracked files, ~13.7k lines |
| JavaScript (ES5-era, no build step) | `lcc_api/static/app.js` | 5,060 lines, single file, no bundler |
| CSS | `lcc_api/static/styles.css` | 4,156 lines, single file |
| HTML | `lcc_api/static/index.html` | 733 lines, served directly |

## Runtime

- Python **>= 3.10** (`pyproject.toml`)
- **uvicorn** ASGI server, launched via `start-lcc.py start` → port **8716**
- **Node** required on PATH *only* to run the JS unit tests (driven from `tests/test_lcc_api.py`)
- No frontend build step, no bundler, no npm dependency tree — `index.html` loads `app.js` directly

## Frameworks

- **FastAPI** — 41 routes, all in `lcc_api/app.py`
- **Pydantic v2** — 13 request models declared inline in `lcc_api/app.py`
- No frontend framework. Vanilla DOM manipulation against a module-global `state` object.

## Key Dependencies

`requirements.txt` is deliberately tiny:

| Package | Constraint | Used for |
|---|---|---|
| `fastapi` | >=0.115.0 | the API |
| `uvicorn[standard]` | >=0.30.0 | serving |
| `pydantic` | >=2.0.0 | request models |
| `gguf` | >=0.19.0 | reading GGUF headers — `lcc_core/truth/gguf.py` |
| `psutil` | >=5.9.0 | process/port detection, RSS in `server_manager.py`, `server_metrics.py` |

Everything else is stdlib or shelled out to an external binary. No ORM, no database driver, no HTTP client library (uses stdlib).

## Configuration

- `models.json` — profile manifest. Entries pin an explicit `model_path`; **no `script` fields** (removed v0.16.0)
- `config.json` — app settings, read via `lcc_core/config.py` (`AppConfig.load()`)
- `pyproject.toml` — packaging + a `slow` pytest marker ("exercises every real GGUF found on disk; deselect with `-m 'not slow'`")
- `.gitattributes` — `* text=auto eol=lf`, with `*.ps1` / `*.bat` forced to CRLF

## Platform Requirements

Windows-first (the author's host), but every hardware probe is per-OS and must degrade rather than raise:

- **NVIDIA** — `nvidia-smi` (7 call sites) for VRAM, utilization, temperature, per-process GPU memory
- **Windows** — `powershell` (3 sites) for CIM hardware queries
- **macOS** — `system_profiler`, `sysctl`
- **Linux** — `lspci`
- **WSL** — `wsl.exe` (4 sites) for the vLLM-in-WSL launch and stop path
