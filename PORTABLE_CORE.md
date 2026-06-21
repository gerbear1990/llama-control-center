# Portable Rebuild Core

This directory now contains an experimental, GitHub-ready core in `lcc_core/`.
It is intentionally separate from the existing Streamlit app so the current
control center can keep working while the replacement architecture is proven.

## Goals

- No source-level paths tied to a single user or machine.
- Discover local runtimes from `PATH`, environment variables, current project
  roots, and standard OS app/cache locations.
- Treat current `models.json` entries as importable profiles, not as the only
  source of truth.
- Provide a JSON inventory contract that a future web UI, desktop app, or TUI
  can use.

## Try It

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

```powershell
python -m lcc_core inventory --pretty
```

To scan explicit model folders:

```powershell
python -m lcc_core inventory --pretty --model-dir D:\Models --model-dir E:\LLMs
```

To point at an existing llama.cpp/control-center root:

```powershell
python -m lcc_core inventory --pretty --project-root C:\path\to\llama.cpp
```

Resolve legacy `models.json` profiles against discovered model files:

```powershell
python -m lcc_core profiles --pretty
```

Build a launch command without starting anything:

```powershell
python -m lcc_core prepare gemma-26b-a4b-q6kxl --pretty
```

Run the local API:

```powershell
python -m lcc_api --host 127.0.0.1 --port 8716
```

Then open:

```text
http://127.0.0.1:8716/
```

The root page serves the lightweight dashboard UI. API docs remain available at
`/docs`.

The dashboard includes:

- a light/dark theme toggle persisted in local browser storage,
- a header hardware widget for detected CPU model, core count, GPU, VRAM, and
  system memory,
- a general settings window for model folders, llama.cpp runtime folders,
  direct llama-server/llama-fit-params paths, default host/port/backend, and
  extra launch args,
- runtime, profile, model, server, log, and portability panels,
- a parameter editor for host, port, context length, threads, batch sizes,
  acceleration backend, device, GPU layers, target and fitted VRAM headroom,
  KV cache types, generation defaults such as
  temperature/top-k/top-p/min-p/repetition penalties/seed/max tokens, draft
  model path, flash attention, reasoning, mmap, KV cache offload, and CPU
  helper offload,
- live memory-fit and tokens/sec estimates for the selected model and current
  parameter choices,
- profile fit badges that classify VRAM/RAM pressure as Good, Tight, or Near
  Limit,
- explicit Prepare/Start actions that use the current parameter values,
- a Hugging Face model-card lookup for a plain-language model summary,
- an explicit fit test action that runs `llama-fit-params` when available,
  parses the fitted command output, and auto-populates matching parameter
  fields such as context, threads, batch/ubatch, GPU layers, KV cache quant,
  sampling defaults, CUDA memory/headroom estimates, and speed estimates,
- a benchmark action that launches or restarts the selected tracked profile
  with current settings, calls the local chat endpoint, and records measured
  tokens/sec.

Run tests:

```powershell
python -m unittest discover -s tests
```

Useful endpoints:

- `GET /health`
- `GET /api/meta`
- `GET /api/inventory`
- `GET /api/profiles`
- `GET /api/config`
- `POST /api/config`
- `GET /api/system`
- `POST /api/estimate/tokens-per-second`
- `POST /api/estimate/launch`
- `GET /api/benchmarks`
- `POST /api/benchmarks/run`
- `POST /api/servers/prepare`
- `POST /api/servers/start`
- `POST /api/profiles/fit`
- `POST /api/models/hf-info`
- `GET /api/servers`
- `POST /api/servers/stop`
- `GET /api/servers/{server_id}/logs`

## Portable Configuration Knobs

Use these only when autodiscovery is not enough:

- `LCC_MODEL_DIRS`: additional model folders, separated by the OS path separator.
- `LCC_CONFIG_DIR`: override the future app config directory.
- `LCC_CACHE_DIR`: override the future app cache directory.
- `LLAMA_CPP_HOME`: root containing llama.cpp binaries.
- `LLAMA_SERVER` or `LLAMA_SERVER_BIN`: full path to `llama-server`.
- `LLAMA_CLI` or `LLAMA_CLI_BIN`: full path to `llama-cli`.
- `LLAMA_FIT_PARAMS` or `LLAMA_FIT_PARAMS_BIN`: full path to `llama-fit-params`.
- `LLAMA_SERVER_URL`: running llama-server API base URL.
- `OLLAMA_HOST`: Ollama API base URL.
- `LMSTUDIO_HOST`: LM Studio API base URL.
- `VLLM_HOST`: vLLM OpenAI-compatible API base URL.
- `HF_HOME`: Hugging Face cache root.

## What It Discovers

- Native llama.cpp binaries and a running llama-server API.
- WSL llama.cpp availability on Windows.
- Ollama, LM Studio, vLLM APIs, and MLX on macOS/Apple Silicon.
- NVIDIA/CUDA GPUs through `nvidia-smi`, plus AMD/Intel/Apple display adapters
  through OS APIs where possible. Acceleration options include CUDA, Vulkan,
  HIP/ROCm, SYCL, Metal, and CPU where applicable.
- GGUF files from targeted model roots.
- Split GGUF bundles, using the first shard as the launchable path.
- Nearby `mmproj*.gguf` projector files.
- Existing `models.json` launch profiles.

## Launch Safety

The new process manager only stops tracked servers that it started and wrote to
its own state file under the portable cache directory. It does not scan for and
kill arbitrary `llama-server` processes.

## Portability Checks

Current local profiles may still contain absolute paths because they represent
this machine's working setup. The new importer reports those as
`portable_warnings` so a future public release can distinguish:

- bundled sample profiles,
- user-local profiles,
- imported legacy profiles.

The inventory also includes `portability_issues`, a best-effort scan of legacy
PowerShell/JSON files for user-specific absolute paths. These are migration
targets, not automatic edits.
