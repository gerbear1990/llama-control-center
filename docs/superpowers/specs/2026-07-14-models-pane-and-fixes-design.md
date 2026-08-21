# Models Pane Actions + Smart-Fit/HF Fixes — Design

**Date:** 2026-07-14
**Status:** Design approved in conversation (models pane + item choices); spec pending user review.
**Target release:** v0.17.0

## Scope

Six items, one release:

1. Models pane actions (approved design)
2. Remove the HF "Install CLI" option
3. Replace the Refresh toolbar icon
4. Fix HF info / update-check for directory checkpoints
5. Built-in MTP detection (launchability + flags)
6. vLLM-WSL fit estimate + full auto-tuner

---

## 1. Models pane actions

Each row in the Models panel gains an action strip; all actions resolve the
model to its auto-registered profile (reuse-auto-profiles approach).

- **Parameters** — select the profile in `#param-profile` (same code path as
  the dropdown) and nav-bounce to the Parameters panel.
- **Fit test** — select, then existing `runFitTest()`.
- **Auto-tune** — select, then existing auto-tune flow.
- **HF check** — select, then existing HF info + update check into Model Notes.
- No matching profile → single **Register** button → `POST /api/profiles/scan`
  → `refresh()` → actions appear.

Matching: pure `profileForModelPath(profiles, path)` — case-insensitive,
slash-agnostic path comparison against `profile.model.path`; when several
profiles share the file, prefer launchable + confidence 1.0, then first.
Unit-tested via the Node-eval pattern used for `formatServerMetricsLine`.

Profiles pane behavior is unchanged; Start still happens through profile
flows after selection.

## 2. Remove HF "Install CLI"

Remove: `#hf-install-button` (index.html:585), its app.js listener
(~app.js:3278-3290), the `POST /api/hf-cli/install` endpoint, and
`install_hf_cli()` in `lcc_core/hf_cli.py` (plus its import in app.py and any
tests). The detect/version/update-check parts of the HF Tools widget stay.
`install_guidance` copy changes to "Run 'pip install huggingface_hub'."
(no longer references a button).

## 3. Refresh icon

`.refresh-icon` (toolbar, index.html:116-118) currently renders a glyph that
doesn't read as "refresh". Replace with a standard circular-arrow refresh
symbol as an inline SVG (two curved arrows / arc with arrowhead), sized to the
existing `.toolbar-icon` box, `currentColor` stroke so both themes work.
CSS-only glyph is removed.

## 4. HF lookup fails for directory checkpoints

**Root cause (verified):** `infer_query("Qwen3.6-27B-NVFP4", path=dir)` uses
`Path(path).stem` — which splits the dotted dir name into `"Qwen3"` — and
appends `parent.name` (`"models"`), producing the failing query
`"Qwen3.6 27B NVFP4 Qwen3 models"`.

**Fix — `infer_query`:**
- Use `path_obj.name` (not `.stem`) when the path has no recognized model
  file suffix (`.gguf`, `.safetensors`, `.bin`) or is a directory name.
- Drop generic folder tokens: `models`, `hf`, `gguf`, `checkpoints`, `weights`.
- De-duplicate tokens already present in `name` (case-insensitive) so the
  query doesn't repeat mangled fragments.

**Fix — `check_model_update` for directories:** when the local path is a
directory (sharded checkpoint), skip the single-file size comparison
(`filename=None`) and compare the repo `lastModified` against the newest
mtime of files inside the directory; report reason accordingly. `fetch_model_info`
needs no change beyond the query fix.

Tests: unit tests for `infer_query` (gguf file, dotted dir, generic parents)
and for the dir branch of `check_model_update` (mocked API payloads, no
network).

## 5. Built-in MTP detection

**Decision (user-confirmed direction, optimal variant):**
- Detect built-in MTP from GGUF metadata/tensor names (NextN / `.mtp` /
  `nextn` tensor markers, plus arch keys where present) via the existing
  gguf-meta cache layer in `estimates.py` — cache-only in the resolver path,
  like `recommend_jinja`.
- If built-in MTP: profiles named/described as MTP **no longer require
  `draft_model`** → `qwen3.6-27b-q6_k-mtp` becomes launchable.
- Force `flash_attn: true` for built-in-MTP models (spec decode requires it).
- **Reasoning and jinja stay on the existing detection** — reasoning derives
  from mode/description, jinja from the actual chat template; coupling them
  to MTP would be less accurate than what already exists.
- Fit estimate counts the MTP head layers (they are in `block_count`; verify
  the estimator doesn't drop them).
- If a profile has an *external* `draft_model` configured, current behavior
  is unchanged.

## 6. vLLM-WSL fit estimate + full auto-tuner

Today `estimates.py`/`smart_tune.py` price everything as llama.cpp GGUF —
meaningless for `vllm-wsl` profiles. This pass adds a vLLM-specific estimator
and makes the auto-tuner search vLLM parameters (user chose the full tuner).

**Estimator (`lcc_core/vllm_estimates.py`):**
- Read the checkpoint's `config.json` (`num_hidden_layers`,
  `num_key_value_heads`, `head_dim` or `hidden_size/num_attention_heads`,
  `max_position_embeddings`, `torch_dtype`, quant config for NVFP4).
- Weights bytes = sum of `*.safetensors` file sizes in the dir (ground truth,
  no bits-per-param guessing).
- KV bytes/token = `2 × layers × kv_heads × head_dim × kv_dtype_bytes`
  (fp16 default; fp8 when `kv_cache_dtype` is set).
- vLLM budget = `VRAM_total × gpu_memory_utilization`; KV pool =
  budget − weights − activation/CUDA-graph overhead (fixed allowance,
  calibrated against the live server's startup log line "GPU KV cache size").
- Fit verdict: `max_model_len × kv_bytes_per_token ≤ kv_pool` → Good/Tight/
  Near-Limit using the same thresholds as the GGUF path; also require
  budget ≤ detected free VRAM (WSL vLLM shares the host GPU — use live free
  VRAM from the hardware poll when available).

**Auto-tuner (extension in `smart_tune.py`):**
- For `runtime == "vllm-wsl"`: greedy search, same shape as the GGUF tuner:
  `gpu_memory_utilization` ladder [0.85, 0.90, 0.92, 0.95] ×
  `max_model_len` ladder (powers up to `max_position_embeddings`) ×
  `max_num_seqs` {1, 2, 4, 8}. Objective: maximize context first, then seqs,
  within a safe-utilization verdict. Before/after summary + per-change
  rationale, one-click apply — same response contract as the GGUF tuner so
  the UI needs no structural change.
- Fit badges for vllm profiles in the Profiles table switch to the new
  estimator.

**Calibration/verification:** compare estimator output against the running
`qwen3.6-27b-nvfp4-vllm` server's actual startup memory report before
trusting the thresholds; record the comparison in the PR/commit message.

## Error handling

- Models pane: action on a model whose profile vanished mid-session → toast
  the scan/register suggestion, never a silent no-op.
- `infer_query` never returns an empty string (falls back to name/dir name).
- vLLM estimator: missing/unparsable `config.json` → `fit_status: unknown`
  with a reason, never a GGUF-based guess; tuner declines with that reason.
- MTP detection is cache-only in the resolver (no GGUF reads on the hot
  path), same rule as `recommend_jinja`.

## Testing

- JS: pure `profileForModelPath` Node-eval test; `node --check`.
- Python: `infer_query` cases; dir-aware update check (mocked); MTP
  detection on synthetic GGUF meta; vLLM estimator math on a fixture
  `config.json` (+ fabricated safetensors sizes); tuner picks within budget
  on the fixture; existing suites stay green.
- Live: models-pane actions drive the real dashboard; vLLM tuner output
  compared against the live vLLM server's memory report.

## Out of scope

- Start/Stop buttons on model rows (explicitly not chosen).
- Ollama, quant picker, app.js modularization (tracked in
  docs/2026-07-14-audit.md).
