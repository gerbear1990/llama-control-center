# Llama Control Center

A lightweight local dashboard for discovering GGUF models, detecting local LLM
runtimes, preparing `llama.cpp` launch commands, running fit tests, and managing
tracked local inference servers.

The app is designed to be portable: paths live in user settings or environment
variables, not in source code.

## Features

- Detects local `llama.cpp`, WSL `llama.cpp`, Ollama, LM Studio, vLLM, and MLX.
- Shows runtime binary/module location, API or probe URL, and port directly on
  runtime cards.
- Finds GGUF models from configured folders, common model folders, LM Studio,
  and Hugging Face cache locations.
- Detects CPU model, core count, system memory, GPU, VRAM, RAM bandwidth, and
  acceleration options.
- Supports NVIDIA/CUDA, AMD and Intel GPU discovery, Apple Metal options on
  macOS, and CPU fallback.
- Resolves `models.json` profiles against discovered local model files.
- Shows profile fit badges: Good, Tight, or Near Limit based on estimated
  accelerator memory and host RAM pressure.
- Provides a parameter editor for context length, threads, batch sizes, GPU
  layers, KV cache quantization, offload toggles, temperature, sampling, and
  more.
- Runs `llama-fit-params` when available and applies parsed recommendations to
  the parameter editor.
- Estimates tokens/sec from the selected model, hardware, and parameters with
  confidence levels based on detected bandwidth data.
- Runs a benchmark against the local OpenAI-compatible chat endpoint to capture
  measured tokens/sec.
- Starts and stops only servers tracked by this app.
- Hugging Face CLI widget: detect, version display, update check, and install
  guidance.
- Draft model suggestions: auto-suggest compatible draft models for speculative
  decoding based on base model size, with one-click pull from Hugging Face.

## Requirements

- Python 3.10 or newer.
- `pip`.
- Optional but recommended: a recent `llama.cpp` build with `llama-server`.
- Optional: `llama-fit-params` for automated fit recommendations.
- Optional: `huggingface-cli` for pulling draft models and HF CLI management.
- Optional runtimes: Ollama, LM Studio, vLLM, or MLX.

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

## Run

Start the local API and dashboard:

```powershell
python -m lcc_api --host 127.0.0.1 --port 8716
```

Open:

```text
http://127.0.0.1:8716/
```

API docs are available at:

```text
http://127.0.0.1:8716/docs
```

## First-Time Setup

1. Open the dashboard.
2. Click **Settings**.
3. Add one or more model folders if autodiscovery does not find your GGUF files.
4. Add runtime folders if `llama-server` or `llama-fit-params` are not on PATH.
5. Save settings and click **Refresh**.

Settings are stored in the operating system's user config directory. Cache data,
tracked server state, logs, and benchmark results are stored in the operating
system's user cache directory.

## Dashboard

The web UI is keyboard-friendly, respects `prefers-reduced-motion`, and ships
with matching light and dark themes. The theme toggle in the top bar persists
your choice in browser storage.

- The sidebar shows navigation, API status, and the running app version.
- The top bar shows the detected CPU, GPU, VRAM, and RAM, plus a search field
  that filters both profiles and models.
- The status strip summarizes runtime count, launchable profile count, total
  model count, and how many items need setup.
- The **Runtimes** panel shows each detected runtime's binary/module location,
  API or probe URL, and port.
- The **Profiles** table is clickable row-by-row and shows fit badges, context
  size, port, and Prepare/Start actions for each profile.
- The **Models** panel lists local GGUF files with quant, size, source, and
  path.
- The right-side inspector holds the **Parameters** editor (with draft model
  suggestions), **Model Notes** (Hugging Face summary and fit-test output),
  tracked **Servers**, **Logs**, **Portability**, and a new **HF Tools** panel
  for Hugging Face CLI management.

Start, Benchmark, and similar destructive actions ask for confirmation through
an in-page modal that supports Escape, Enter, and Tab focus trapping.

## Environment Variables

Use these when you want repeatable setup without editing settings in the UI:

- `LCC_MODEL_DIRS`: model folders separated by the OS path separator.
- `LCC_CONFIG_DIR`: override the app config directory.
- `LCC_CACHE_DIR`: override the app cache directory.
- `LLAMA_CPP_HOME`: folder containing `llama.cpp` binaries.
- `LLAMA_SERVER` or `LLAMA_SERVER_BIN`: full path to `llama-server`.
- `LLAMA_CLI` or `LLAMA_CLI_BIN`: full path to `llama-cli`.
- `LLAMA_FIT_PARAMS` or `LLAMA_FIT_PARAMS_BIN`: full path to
  `llama-fit-params`.
- `LLAMA_SERVER_URL`: existing llama-server API base URL.
- `OLLAMA_HOST`: Ollama API base URL.
- `LMSTUDIO_HOST`: LM Studio API base URL.
- `VLLM_HOST`: vLLM OpenAI-compatible API base URL.
- `HF_HOME`: Hugging Face cache root.

## Models And Profiles

The app scans targeted model roots for `.gguf` files. It avoids broad whole-disk
or whole-home scans.

If a `models.json` file exists near the project root, entries are imported as
profiles. Profiles are resolved against discovered model files by name, quant,
size, and path hints. Unresolved or ambiguous profiles are shown as setup items
instead of being silently launched.

## Fit Tests

The **Fit test** button runs `llama-fit-params` for the selected profile when
available. Parsed recommendations update compatible fields automatically,
including:

- context length
- threads and batch threads
- batch and ubatch
- GPU layers
- KV cache quantization
- KV/cache offload toggles
- sampling defaults
- fitted VRAM headroom

The live Memory Fit card updates whenever you change parameters manually.

## Benchmarks

The **Benchmark** button starts or restarts the selected tracked profile with
the current parameters, sends a fixed local chat request, and records:

- measured completion tokens/sec
- elapsed seconds
- generated token count
- prompt and total tokens when reported by the server
- character throughput
- endpoint used

Benchmarks are meant to measure the current machine and runtime. They are more
precise than the live estimate, but still depend on background load, prompt
shape, and the exact `llama.cpp` build.

## Safety

The process manager only stops servers that this app started and recorded in
its own state file. It does not scan for or kill arbitrary `llama-server`
processes.

## Acknowledgements

This project is built around the local inference ecosystem created by projects
such as `llama.cpp`, Ollama, LM Studio, vLLM, MLX, Hugging Face, FastAPI, and
Uvicorn.

The product direction was inspired in part by Alex Jones' `llama-panel`,
`llmfit`, and `llmserve` projects. No source code from those repositories has
been copied or vendored into this repository at this stage.

## License

MIT. See [`LICENSE`](./LICENSE) for the full text.

## Development

Run tests:

```powershell
python -m unittest discover -s tests
```

Check the static JavaScript:

```powershell
node --check .\lcc_api\static\app.js
```

Run the portable inventory from the command line:

```powershell
python -m lcc_core inventory --pretty
```

Resolve profiles:

```powershell
python -m lcc_core profiles --pretty
```
