---
description: "Llama Control Center — external integrations"
type: CodebaseDoc
about: "llama-control-center"
---

# External Integrations

## APIs & External Services

| Service | Endpoint | Used by | Purpose |
|---|---|---|---|
| Hugging Face | `https://huggingface.co/api/models/{repo_id}` | `hf_metadata.py` | repo resolution, file listing, model update checks |
| Hugging Face | `https://huggingface.co` | `hf_cli.py`, `draft_models.py` | downloads, draft-model suggestions |
| GitHub Releases | `https://api.github.com/repos/{repo}/releases[/latest]` | `runtime_updates.py` | runtime version checks (stable/prerelease channel) |
| PyPI | `https://pypi.org/pypi/huggingface_hub/json` | `hf_cli.py` | HF CLI update check |

All are **unauthenticated public reads** and all are best-effort — `runtime_updates.py` is documented as "best-effort runtime update checks against public release sources". A network failure degrades the card; it must not fail a page load.

## Local Runtimes Controlled

| Runtime | Launched via | Notes |
|---|---|---|
| llama.cpp | `llama_args.py` → `server_manager.py` | the primary path |
| vLLM (in WSL) | `vllm_args.py` + `wsl.exe` (4 call sites) | launch *and* a `wsl.exe` stop script |
| MLX | backend detection in `backends.py` | macOS |

Servers spawn **detached** (`start_new_session`) so they outlive the control center.

## External Binaries

| Binary | Calls | Platform | Purpose |
|---|---|---|---|
| `nvidia-smi` | 7 | NVIDIA | VRAM/util/temp; `--query-compute-apps` for per-process GPU memory |
| `wsl.exe` | 4 | Windows | vLLM launch + stop |
| `huggingface-cli` / `hf` | 3 + 1 | any | model pulls when present |
| `powershell` | 3 | Windows | CIM hardware queries |
| `system_profiler`, `sysctl` | 2 + 1 | macOS | hardware probe |
| `lspci` | 2 | Linux | GPU enumeration |
| `node` | test-only | any | runs the JS unit tests from pytest |

Every one of these is optional at runtime. Absence must degrade the answer, not raise.

## Data Storage

**Files only — no database.**

| File | Contents |
|---|---|
| `models.json` | profile manifest; entries pin explicit `model_path` (no `script` fields since v0.16.0) |
| `config.json` | app settings, via `AppConfig.load()` in `config.py` |
| tracked-server state file | pid/port/log paths, read-write-trimmed by `server_manager.py` |
| per-server stderr logs | captured on launch, served by `GET /api/servers/{id}/logs` |
| GGUF metadata cache | keyed on `(size, mtime)`; the paused plan bumps it to v4 for an `mtp` flag |

## Authentication & Identity

**None.** No auth layer, no sessions, no API keys in the codebase. The dashboard binds locally (:8716) and assumes a single trusted operator on the host. Treat any exposure beyond localhost as an explicit, currently-unbuilt feature.

## Monitoring & Observability

Self-observation of launched servers rather than external telemetry:

- `server_metrics.py` polls the running server's `/metrics` (Prometheus), `/health`, `/props` for KV usage, slots in use, decode tokens/sec, context fill
- `psutil` RSS + `nvidia-smi --query-compute-apps` for the `process` block
- `refresh_server_states()` keeps a 10-sample rolling RAM window and annotates freshly-crashed servers with `oom_likely` when peak pressure exceeded 80%
- `GET /api/system/live` — host GPU util/temp/VRAM + system RAM, 2s TTL behind a lock

No outbound telemetry. Nothing phones home.

## Downstream Consumers

**OpenCode** — LCC-spun llama.cpp servers are registered as providers in `~/.config/opencode/opencode.jsonc` (`lcc_default_port` / `lcc_alt_port`, ports 8080/8081) with model IDs matching the `--alias {profile.mode}` convention. Currently **manual**: a new profile mode needs a hand JSONC edit. Auto-sync on start/stop is backlog item M5.3.

## CI/CD & Deployment

No CI configuration in the repo. Tests are run locally; releases are manual (version bump in `lcc_api/__init__.py` + `pyproject.toml`, CHANGELOG, tag, push). Broader CI is backlog item M5.4.

⚠️ `index.html` carries a hand-bumped cache-buster, currently **`?v=0.16.17`**, while
`lcc_api.__version__` is **`0.16.0`** — the two have drifted apart and now disagree. (The audit
recorded this as `?v=0.15.0`; it has been bumped independently since.) Deriving it from
`lcc_api.__version__` at template-serve time is scheduled in Phase 6.
