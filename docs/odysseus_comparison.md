# Odysseus vs LCC: Feature Comparison & Migration Plan

Generated: 2026-07-02

This document compares the hardware probing, model fit estimation, speed modeling, and ranking systems of the Odysseus project (`dev/odysseus`) against the llama.cpp Control Center (`lcc_core`). It documents what Odysseus does well, what LCC does better, and which features are worth porting.

---

## 1. Hardware Detection

### Odysseus (services/hwfit/hardware.py)

- **NVIDIA**: `nvidia-smi --query-gpu=memory.total,name --format=csv,noheader,nounits` with 3 fallback strategies for SSH/WSL environments
- **Windows**: PowerShell `Get-CimInstance Win32_VideoController`
- **Mac**: `system_profiler SPMemoryDataType` + `sysctl` for CPU
- **Linux**: `/proc/cpuinfo` parsing for CPU, `lshw`/`nvidia-smi` for GPUs
- **VRAM bandwidth**: Computed from GPU name lookup tables (bus width + data rate)
- **Grouping**: Groups identical GPUs by (name, rounded VRAM) for tensor-parallel awareness
- **Caching**: 24-hour TTL on hardware probes (cached to disk)
- **Remote support**: SSH-based detection for remote hosts

### LCC (lcc_core/hardware.py)

- **NVIDIA**: `nvidia-smi` with detailed query: `index,name,memory.total,memory.free,driver_version,clocks.current.memory,clocks.max.memory` — includes VRAM **free** memory and clock speeds
- **Windows**: PowerShell Win32_VideoController + detailed PNPDeviceID parsing (VEN/DEV/REV) for exact bus width and data rate lookup
- **AMD**: Full support via `_amd_bus_width()` and `_amd_data_rate()` with device ID maps for RX 5000-9000 (RDNA 1-4)
- **Intel**: Supported with Arc series detection
- **Mac**: `system_profiler SPMemoryDataType` AND `SPDisplaysDataType`
- **Linux**: `lspci` fallback with vendor-specific bus width and data rate guessing
- **RAM speed/bandwidth**: Platform-specific detection (PowerShell on Windows, `system_profiler` on Mac, `dmidecode` on Linux)
- **VRAM clocks**: `clocks.current.memory` and `clocks.max.memory` from nvidia-smi
- **Virtual display filtering**: Drops "virtual monitor", "spacedesk", "parsec", etc.
- **GPU deduplication**: Based on vendor:name normalization
- **No caching**: Always probes fresh

### Key Differences

| Feature | Odysseus | LCC |
|---------|----------|-----|
| VRAM free memory | No | Yes |
| VRAM clock speeds | No | Yes |
| RAM speed/bandwidth | No | Yes (all platforms) |
| AMD GPU support | Minimal | Full (RX 5000-9000) |
| Intel GPU support | No | Arc A380/A750/A770 |
| Revision ID detection | No | Yes (PNPDeviceID) |
| GPU grouping for TP | Yes | No (dedup only) |
| SSH/remote detection | Yes | No |
| Caching | 24h TTL | None (always fresh) |
| Virtual display filter | No | Yes |

---

## 2. Model Discovery

### Odysseus (services/hwfit/models.py)

- **Remote catalog**: Loads from bundled `hf_models.json` — curated list of HuggingFace models
- **Metadata**: Parameter count, use case, release date, context length, provider
- **Quant inference**: `infer_quantization_from_name()` parses model names to detect AWQ, GPTQ, MLX, FP8, FP4, NVFP4, MXFP4, NF4, INT4/8, W4A16/W8A8, W8A16
- **Use case inference**: `infer_use_case()` detects coding, reasoning, multimodal, embedding, chat, tts, stt from model name/description
- **MoE support**: `is_moe` flag and `active_parameters` field
- **Pre-quantized detection**: `is_prequantized()` distinguishes native HF formats from GGUF tiers
- **Pre-quantized prefixes**: `AWQ-`, `GPTQ-`, `mlx-`, `FP8`, `FP4`, `NVFP4`, `MXFP4`, `NF4`, `INT4`, `INT8`, `W4A16`, `W8A8`, `W8A16`, `FP4-MoE-Mixed`, `FP8-Mixed`, `QAT-`

### LCC (lcc_core/models.py)

- **Local discovery**: Scans configured directories for `.gguf` files
- **Filename parsing**: Extracts quant (Q4_K_M, Q8_0, etc.) and parameter count (27B, 70B, etc.)
- **Split GGUF support**: Handles `*-00001-of-00005.gguf`
- **mmproj detection**: Finds vision model projectors
- **Source tracking**: Distinguishes custom vs. known model directories
- **No remote catalog**: Purely local

### Key Difference

Odysseus = remote catalog with inference. LCC = local file discovery. Complementary approaches. LCC doesn't need a remote catalog, but the quant inference and pre-quantized format tables from Odysseus are useful.

---

## 3. Model Fit / Memory Estimation

### Odysseus (services/hwfit/fit.py)

- **Formula**: `params_b * bpp + 0.000008 * active_params * ctx + 0.5`
- **bpp**: From `QUANT_BPP` table (Q4_K_M=0.58, Q8_0=1.05, FP4=0.5, etc.)
- **No GGUF header parsing**: Everything is heuristic-based
- **run_mode**: "gpu", "cpu_offload", "cpu_only" — determines how the model runs
- **fit_level**: "perfect" (fits with 20%+ headroom), "good" (fits on VRAM or 20% RAM headroom), "marginal" (barely fits), "too_tight" (doesn't fit)
- **Offload fraction**: `offload_frac = (required_gb - effective_vram) / required_gb` for speed blending
- **best_quant_for_budget()**: Iterates through QUANT_HIERARCHY to find best quant that fits
- **MoE-aware**: Uses `active_params` for KV cache and speed, total params for VRAM
- **Multi-GPU awareness**: Single-GPU VRAM for GGUF/dense, full multi-GPU VRAM for pre-quantized (sharded by vLLM)
- **GPU-only mode**: `gpu_only` flag disables offload budget, forcing VRAM-only fit checks

### LCC (lcc_core/estimates.py)

- **GGUF header parsing**: Reads actual `n_layer`, `kv_dims` (total_kv_heads, k_dim, v_dim) from GGUF files via the `gguf` Python library
- **Exact KV cache sizing**: `ctx * (total_kv_heads * k_dim * cache_k + total_kv_heads * v_dim * cache_v) / 1024 / 1024`
- **Hybrid architecture support**: Handles Qwen3.5-style SSM+attention by counting only attention layers for KV cache
- **Per-layer fraction model**: `layer_fraction = gpu_layers / total_layers` — models exact VRAM/RAM split
- **Detailed breakdown**: Separates `accelerator_used_mib`, `host_used_mib`, `compute_mib`, `kv_cache_mib`, `model_size_mib`
- **Offload awareness**: Handles `kv_offload`, `op_offload`, `mmap` flags and their effect on VRAM vs RAM split
- **Status labels**: "Good", "Tight", "Near Limit" based on headroom
- **Caching**: On-disk JSON cache keyed by (size, mtime) so GGUF parsing is a one-time cost per file
- **Fallback factor**: 0.012 when exact dims unavailable (between dense attention ~0.036 and GQA ~0.005)

### Key Difference

LCC's fit estimation is **orders of magnitude more accurate** because it reads actual GGUF metadata. Odysseus uses a rough heuristic that's fast but less precise. LCC's per-component breakdown (compute, KV cache, model weights) is also superior for troubleshooting.

However, Odysseus's **run_mode** and **fit_level** concepts are more actionable than LCC's status labels. "CPU offload with 30% spill" tells a user more than "Tight".

---

## 4. Speed Estimation

### Odysseus (services/hwfit/fit.py)

- **Formula (GPU)**: `tps = (bandwidth / model_gb) * 0.55` (efficiency factor 0.55)
- **Formula (offload)**: Harmonic blend — `eff_bw = 1.0 / (frac / cpu_bw + (1.0 - frac) / bw)` where `cpu_bw = 55.0` GB/s
- **Quant speed multiplier**: `QUANT_SPEED_MULT` table (Q4_K_M=1.15, Q8_0=0.8, FP4=1.15, etc.)
- **MoE penalty**: 0.8x speed for MoE models (due to expert dispatch overhead)
- **Fallback**: `FALLBACK_K` dict — cuda=220, rocm=180, metal=150, cpu_x86=70, cpu_arm=90
- **Architecture bonus**: +9 for Qwen3.6, +8 for Qwen3.5, +6 for Qwen3-next, +4 for Qwen3, +2 for Qwen2.5
- **CPU backend normalization**: `_canonical_cpu_backend()` maps x86_64/amd64 to cpu_x86, arm64/aarch64 to cpu_arm

### LCC (lcc_core/estimates.py)

- **GPU decode**: `1140 * gpu_factor * quant_factor / sqrt(model_params_b)` — model-size-aware
- **CPU decode**: `9.0 * sqrt(logical_cores) / sqrt(model_params_b)` — core-count aware
- **Blended**: `gpu_decode * layer_fraction^1.35 + cpu_decode * (1 - layer_fraction)`
- **Context penalty**: `ctx_factor = max(0.72, 1.0 - min(ctx, 262144) / 262144 * 0.18)`
- **Batch/ubatch effects**: `batch_factor` adjusts for batch size, ubatch < 256 penalty, flash attention bonus
- **Offload penalties**: kv_offload disabled = 0.74x, op_offload disabled = 0.9x
- **Bandwidth ceiling**: Actual measured VRAM/RAM bandwidth applied as hard cap on TPS
- **Confidence levels**: high/medium/low based on whether bandwidth data exists
- **Draft model**: 1.08x speedup for speculative decoding
- **Per-GPU-factor**: 5090=1.2, 4090=1.0, 3090=0.76, 4070=0.43, AMD=0.36, Intel=0.28

### Key Difference

LCC's speed model is more sophisticated — it accounts for context length, batch size, layer fraction, offload flags, draft models, AND applies real bandwidth measurements as hard ceilings. Odysseus uses a single bandwidth/model_size formula.

However, Odysseus's **harmonic blend for offload** is more physically accurate than LCC's power-law blend. When part of the model spills to CPU RAM, the per-token time is dominated by the slow CPU path — the harmonic blend captures this steep drop-off better.

---

## 5. GPU Bandwidth Lookup Tables

### Odysseus

Comprehensive `GPU_BANDWIDTH` dict covering:
- **RTX 50 series**: 5090=1792, 5080=960, 5070ti=896, 5070=672, 5060ti=448, 5060=256
- **RTX 40 series**: 4090=1008, 4080S=736, 4080=717, 4070TiS=672, 4070Ti=504, 4070S=504, 4070=504, 4060Ti=288, 4060=272
- **RTX 30 series**: 3090Ti=1008, 3090=936, 3080Ti=912, 3080=760, 3070Ti=608, 3070=448, 3060Ti=448, 3060=360, 3050Ti=192, 3050=224
- **RTX 20/16 series**: 2080Ti=616, 2080S=496, 2080=448, 1660Ti=288, 1660S=336, 1660=192, 1650S=192, 1650=128
- **Datacenter**: H100 SXM=3350, H100=2039, H200=4800, A100 SXM=2039, A100=1555, L40s=864, A10G=600, T4=320, V100 SXM=900, A6000=768
- **AMD RX 7000**: 7900XTX=960, 7900XT=800, 7900GRE=576, 7800XT=624, 7700XT=432, 7600=288
- **AMD RX 6000**: 6950XT=576, 6900XT=512, 6800XT=512, 6800=512, 6700XT=384, 6600XT=256
- **AMD MI**: MI300X=5300, MI250X=3277, MI210=1638
- **AMD RX 9000**: 9070XT=624, 9070=488, 9060XT=322, 9060=322
- **Apple Silicon**: M1 Ultra=800, M1 Max=400, M1 Pro=200, M1=68, M2 Ultra=800, M3 Ultra=800, M4 Pro=273
- **Apple core-count aware**: M3 Max 30-core=300/40-core=400, M4 Max 32-core=410/40-core=546, M5 Max 32-core=460/40-core=614
- **Grace-Blackwell**: GB10=273

### LCC

Uses `_gpu_factor()` multiplier (abstract, not GB/s):
- 5090=1.2, 4090=1.0, 3090=0.76, 4080=0.76, 3080=0.58, 4070=0.43, 3070=0.43, 4060=0.43
- AMD=0.36, Intel=0.28, Apple=0.64 (hardcoded minimum for Metal)

LCC also extracts real bandwidth from `nvidia-smi` clocks + PNPDeviceID lookup tables, but Odysseus's tables are more comprehensive and serve as a better fallback.

---

## 6. Scoring & Ranking

### Odysseus (services/hwfit/fit.py)

- **Quality score**: Based on parameter count (1B=30, 3B=45, 7B=60, 10B=75, 20B=82, 40B=89, 80B=95), model family bonuses (Qwen+2, DeepSeek+3, Llama+2, Mistral+1, Gemma+1), architecture bonus (Qwen3.6+9, Qwen3.5+8, Qwen3+4, Qwen2.5+2), quant quality penalty, and use-case match bonus
- **Speed score**: `tps / target_tps * 100` where target varies by use case (general=40, reasoning=25, embedding=200)
- **Fit score**: Ratio-based — ratio <= 0.5: 60-100, ratio <= 0.8: 100, ratio <= 0.9: 70, else 50
- **Context score**: Target vs. available (general=4096, coding=8192, reasoning=8192, embedding=512)
- **Use-case weights**: general=(0.45, 0.30, 0.15, 0.10), coding=(0.50, 0.20, 0.15, 0.15), reasoning=(0.55, 0.15, 0.15, 0.15), chat=(0.40, 0.35, 0.15, 0.10), embedding=(0.30, 0.40, 0.20, 0.10)
- **Version-aware sorting**: `_version_key()` parses version numbers from model names for tiebreaking

### LCC

- No model ranking or scoring
- `_score()` in `profile_resolver.py` is just a token-overlap matcher for profile-to-model matching, not hardware-aware
- No use-case awareness
- No quality/speed/fit/context breakdowns

---

## 7. Auto-Tuning

### LCC (lcc_core/smart_tune.py)

- **Grid search**: 5 layer options x 9 context sizes x 4 K cache x 4 V cache = ~720 combinations
- **Three intents**: "balanced" (KV quality leaning), "max_quality" (best KV cache), "max_context" (largest window)
- **Batch refinement**: Grows batch/ubatch into leftover headroom
- **Thread recommendation**: Physical cores for decode, logical cores for prompt batches
- **Jinja recommendation**: Auto-detects whether model needs jinja chat template
- **Before/after comparison**: Shows what changed and why

### Odysseus

- No auto-tuning. Only analytical estimation.

---

## 8. Runtime Fit Testing

### LCC (lcc_core/fit.py)

- Calls `llama-fit-params` binary from llama.cpp
- Parses output for fitted CLI arguments, CUDA memory breakdown, free VRAM, headroom
- Can auto-apply fitted suggestions to launch parameters

### Odysseus

- No runtime fit testing. Everything is analytical/heuristic.

---

## Feature Gaps: What LCC Is Missing

### A. Pre-Quantized Format Support

LCC only handles GGUF quants. Missing: AWQ, GPTQ, MLX, FP8 (native HF), FP4, NVFP4, MXFP4, NF4, INT4/8, W4A16/W8A8, W8A16, QAT.

**Required tables from Odysseus:**
- `QUANT_QUALITY_PENALTY` — quality impact of each quant format
- `QUANT_SPEED_MULT` — speed multiplier for each quant format
- `QUANT_BYTES_PER_PARAM` — bytes per parameter for memory estimation
- `QUANT_HIERARCHY` — ranked order of GGUF quants (Q8_0 > Q6_K > Q5_K_M > Q4_K_M > ...)
- `PREQUANTIZED_PREFIXES` — formats that shouldn't go through GGUF quant hierarchy
- `infer_quantization_from_name()` — parse model names to detect format
- `is_prequantized()` — distinguish native HF formats from GGUF tiers
- `_quant_bits()` — approximate bit-width for cross-format comparison

### B. MoE-Aware Fit Estimation

LCC's fit estimation treats all models as dense. For MoE models (DeepSeek, Mixtral, Qwen3-MoE), it should use `active_params` for KV cache and speed calculations while keeping total params for VRAM.

**Required from Odysseus:**
- `is_moe` detection from GGUF `n_experts` and `n_experts_used` fields
- `_active_params_b()` — returns active params for MoE, total for dense
- Use active params in KV cache formula: `0.000008 * active_params * ctx`
- Speed penalty for MoE: 0.8x (expert dispatch overhead)

### C. Run Mode & Fit Level Granularity

LCC uses "Good/Tight/Near Limit" which is informative but not as actionable as Odysseus's fit levels and run modes.

**Recommended fit levels:**
- "perfect" — fits with 20%+ headroom on GPU
- "good" — fits on GPU with <20% headroom, or fits with 20%+ RAM headroom
- "marginal" — barely fits (ratio 0.8-1.0)
- "too_tight" — doesn't fit at all

**Run modes:**
- "gpu" — fully on GPU VRAM
- "cpu_offload" — partial GPU, rest on system RAM
- "cpu_only" — entirely on CPU

### D. Use-Case-Aware Analysis

Odysseus infers use case from model name/description and adjusts scoring accordingly. While LCC doesn't need a full ranking system, per-model use-case tags could inform fit recommendations and warnings.

**Use cases:** coding, reasoning, multimodal, embedding, chat, tts, stt, general

### E. Comprehensive GPU Bandwidth Fallback Tables

LCC's `_gpu_factor()` is a rough heuristic. Odysseus's per-card bandwidth table (in GB/s) is more precise and covers many more cards. Useful as a fallback when `nvidia-smi` clocks are unavailable or PNPDeviceID lookup fails.

---

## What LCC Does Better (Keep These)

1. **GGUF header parsing** — LCC reads actual KV dimensions from GGUF files. Odysseus's heuristic formula is too rough.
2. **RAM speed detection** — LCC detects DDR type, speed, and computes bandwidth on all platforms. Odysseus doesn't.
3. **AMD GPU support** — LCC has full RDNA 1-4 support with device ID maps. Odysseus has minimal.
4. **VRAM free memory** — LCC extracts free VRAM from nvidia-smi. Odysseus only sees total.
5. **Auto-tuning** — LCC's `smart_tune.py` grid search with balanced/quality/context intents is excellent. Odysseus has no equivalent.
6. **Runtime fit testing** — LCC calls `llama-fit-params` for ground-truth measurements. Odysseus is purely analytical.
7. **Per-component memory breakdown** — LCC separates model, KV cache, compute, and headroom. Odysseus gives a single number.
8. **Bandwidth ceiling on speed** — LCC applies measured VRAM/RAM bandwidth as hard TPS cap. Odysseus doesn't.
9. **Context/batch/offload effects** — LCC's speed model accounts for 8+ parameters. Odysseus uses a flat formula.

---

## Migration Plan: Top 3 Priorities

### Priority 1: Pre-Quantized Format Support

**Impact**: Makes LCC useful for AWQ/GPTQ/FP8 models which are common for many popular models.

**Changes needed:**
1. Add `QUANT_QUALITY_PENALTY`, `QUANT_SPEED_MULT`, `QUANT_BYTES_PER_PARAM`, `QUANT_HIERARCHY`, `PREQUANTIZED_PREFIXES` tables to `estimates.py` (or a new `formats.py` module)
2. Add `infer_quantization_from_name()` to `models.py`
3. Add `is_prequantized()` to `models.py`
4. Update `QUANT_FACTORS` in `estimates.py` to cover pre-quantized formats
5. Update `QUANT_BPP_FALLBACK` (if any) in `estimates.py`

**Files to modify:** `lcc_core/estimates.py`, `lcc_core/models.py`

### Priority 2: MoE-Aware Fit Estimation

**Impact**: Critical for accurate estimates on DeepSeek, Mixtral, Qwen3-MoE, etc.

**Changes needed:**
1. Read `n_experts` and `n_experts_used` from GGUF header in `models.py`
2. Add `is_moe` flag to model dicts
3. Add `active_params_b()` function to `models.py`
4. Update `estimate_memory_fit()` in `estimates.py` to use active params for KV cache when model is MoE
5. Add 0.8x speed penalty for MoE in `estimate_tokens_per_second()`

**Files to modify:** `lcc_core/models.py`, `lcc_core/estimates.py`

### Priority 3: Fit Level & Run Mode Granularity

**Impact**: More actionable fit information for users.

**Changes needed:**
1. Replace "Good/Tight/Near Limit" with "perfect/good/marginal/too_tight"
2. Add `run_mode` field: "gpu", "cpu_offload", "cpu_only"
3. Add `fit_level` field to `estimate_memory_fit()` return dict
4. Add fit ratio calculation (required/available) for each level
5. Update `_status_from_headroom()` to use ratio-based thresholds

**Files to modify:** `lcc_core/estimates.py`

### Low Priority: GPU Bandwidth Fallback Tables

**Impact**: Better fallback when hardware detection fails.

**Changes needed:**
1. Add `GPU_BANDWIDTH` dict to `hardware.py` (from Odysseus)
2. Add `APPLE_BANDWIDTH_FIXED` and `APPLE_BANDWIDTH_BY_CORES` dicts
3. Add `_fallback_gpu_bandwidth()` function that checks the table before returning None
4. Use in `estimate_tokens_per_second()` when `vram_bandwidth_gbps` is None

**Files to modify:** `lcc_core/hardware.py`

---

## Reference: Odysseus Quantization Tables

### QUANT_BPP (bits per param for memory)

```
F32: 4.0, F16: 2.0, BF16: 2.0, FP8: 1.0
FP4/NVFP4/MXFP4/NF4/INT4/W4A16: 0.50
INT8/W8A8/W8A16: 1.0
Q8_0: 1.05, Q6_K: 0.80, Q5_K_M: 0.68
Q4_K_M: 0.58, Q4_0: 0.58, Q3_K_M: 0.48, Q2_K: 0.37
AWQ-4bit/GPTQ-Int4/QAT-INT4/MLX-4bit: 0.50
AWQ-8bit/GPTQ-Int8/MLX-8bit: 1.0
MLX-6bit: 0.75
FP4-MoE-Mixed: 0.55
```

### QUANT_QUALITY_PENALTY (impact on quality score)

```
F16/BF16/FP8/Q8_0/INT8/W8A8/W8A16/QAT-INT8: 0.0
Q6_K: -1.0
AWQ: -1.0, AWQ-8bit: -1.0, GPTQ: -1.0, GPTQ-Int8: -1.0
QAT-INT4: -1.0, MLX-6bit: -1.5, MLX-8bit: -0.5
Q5_K_M: -2.0
Q4_K_M/Q4_0: -5.0
Q3_K_M: -8.0
Q2_K: -12.0
FP4/NVFP4/MXFP4: -3.0
NF4/INT4: -4.0
W4A16: -4.0
FP4-MoE-Mixed: -0.5
```

### QUANT_SPEED_MULT (relative decode speed, Q5_K_M = baseline 1.0)

```
Q8_0: 0.8, F16/BF16: 0.6, FP8/INT8/W8A8/W8A16: 0.85
Q6_K: 0.95, MLX-6bit: 1.0
Q5_K_M: 1.0 (baseline)
Q4_K_M/Q4_0/INT4/NF4/FP4/NVFP4/MXFP4/W4A16/MLX-4bit: 1.15
GPTQ-Int4/AWQ-4bit/QAT-INT4: 1.2
Q3_K_M: 1.25
Q2_K: 1.35
FP4-MoE-Mixed: 1.10
```

### QUANT_BYTES_PER_PARAM (for memory estimation in GB)

```
F16/BF16: 2.0, FP8/INT8/W8A8/W8A16: 1.0
FP4/NVFP4/MXFP4/NF4/INT4/W4A16: 0.5
Q8_0: 1.0, Q6_K: 0.75, Q5_K_M: 0.625
Q4_K_M/Q4_0: 0.5, Q3_K_M: 0.375, Q2_K: 0.25
AWQ-4bit/GPTQ-Int4/MLX-4bit: 0.5, AWQ-8bit/GPTQ-Int8/MLX-8bit: 1.0
MLX-6bit: 0.75, FP4-MoE-Mixed: 0.55
```

### QUANT_HIERARCHY (best quality to worst for auto-selection)

```
Q8_0 > Q6_K > Q5_K_M > Q4_K_M > Q3_K_M > Q2_K
```

### GPU_BANDWIDTH (GB/s, selected entries)

```
RTX 5090: 1792, 5080: 960, 5070 Ti: 896, 5070: 672, 5060 Ti: 448, 5060: 256
RTX 4090: 1008, 4080 Super: 736, 4080: 717, 4070 Ti Super: 672, 4070 Ti: 504, 4070 Super: 504, 4070: 504, 4060 Ti: 288, 4060: 272
RTX 3090 Ti: 1008, 3090: 936, 3080 Ti: 912, 3080: 760, 3070 Ti: 608, 3070: 448, 3060 Ti: 448, 3060: 360
RTX 2080 Ti: 616, 2080 Super: 496, 2080: 448, 1660 Ti: 288, 1660 Super: 336, 1660: 192, 1650: 128
H100 SXM: 3350, H100: 2039, H200: 4800, A100 SXM: 2039, A100: 1555, A6000: 768, L40s: 864, T4: 320, V100 SXM: 900
RX 7900 XTX: 960, 7900 XT: 800, 7900 GRE: 576, 7800 XT: 624, 7700 XT: 432, 7600: 288
RX 6950 XT: 576, 6900 XT: 512, 6800 XT: 512, 6800: 512, 6700 XT: 384, 6600 XT: 256
MI300X: 5300, MI250X: 3277, MI210: 1638
9070 XT: 624, 9070: 488, 9060 XT: 322, 9060: 322
M1 Ultra: 800, M1 Max: 400, M1 Pro: 200, M1: 68
M2 Ultra: 800, M2 Max: 400, M2 Pro: 200, M2: 100
M3 Ultra: 800, M3 Max 40-core: 400, M3 Max 30-core: 300, M3 Pro: 150, M3: 100
M4 Pro: 273, M4 Max 40-core: 546, M4 Max 32-core: 410, M4: 120
M5 Pro: 307, M5 Max 40-core: 614, M5 Max 32-core: 460, M5: 153
GB10 (Grace-Blackwell): 273
```
