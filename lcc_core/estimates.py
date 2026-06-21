from __future__ import annotations

import math
import os
import re
from typing import Any


QUANT_FACTORS = {
    "Q2": 1.28,
    "Q3": 1.16,
    "Q4": 1.0,
    "IQ4": 1.0,
    "Q5": 0.9,
    "Q6": 0.78,
    "Q8": 0.62,
    "F16": 0.42,
    "BF16": 0.42,
    "F32": 0.24,
}

CACHE_BYTES = {
    "F32": 4.0,
    "F16": 2.0,
    "BF16": 2.0,
    "Q8_0": 1.06,
    "Q5_1": 0.70,
    "Q5_0": 0.66,
    "Q4_1": 0.56,
    "Q4_0": 0.53,
    "IQ4_NL": 0.52,
}

# GGUF tensor name patterns that reveal n_layer
_N_LAYER_PATTERNS = [
    r"\.h\[(\d+)\]\.",
    r"transformer\.layer\.(\d+)\.",
    r"model\.layers\.(\d+)\.",
    r"blk\.(\d+)\.",
    r"block\.(\d+)\.",
]


def _read_gguf_n_layer(model_path: str | None) -> int | None:
    """Read the actual number of transformer layers from a GGUF file header.
    
    First tries architecture-specific KV keys (e.g. 'llama.block_count',
    'gemma4.block_count'), then falls back to scanning tensor names for
    the highest layer index.
    """
    if not model_path:
        return None
    try:
        import gguf as _gguf
        reader = _gguf.GGUFReader(str(model_path))

        def _field_value(field):
            """Extract the actual value from a ReaderField."""
            if field is None or not field.parts:
                return None
            # The last part contains the actual value bytes
            last_part = field.parts[-1]
            if hasattr(last_part, "tobytes"):
                raw = last_part.tobytes()
                if not raw:
                    return None
                # Try to interpret as integer
                if len(raw) <= 8:
                    return int.from_bytes(raw, "little")
                # String value
                return raw.decode("utf-8", errors="replace").strip("\x00")
            return None

        # Get architecture name
        arch_field = reader.get_field("general.architecture")
        arch = _field_value(arch_field)

        if arch:
            for key_suffix in ("block_count", "n_layer"):
                full_key = f"{arch}.{key_suffix}"
                field = reader.get_field(full_key)
                val = _field_value(field)
                if isinstance(val, int) and val > 0:
                    return val

        # Fall back: scan tensor names for blk.N or block.N indices
        max_layer = -1
        for tensor in reader.tensors:
            name = tensor.name
            for pattern in _N_LAYER_PATTERNS:
                m = re.search(pattern, name)
                if m:
                    idx = int(m.group(1))
                    if idx > max_layer:
                        max_layer = idx
                    break

        if max_layer >= 0:
            return max_layer + 1
        return None
    except Exception:
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _model_params_b(model: dict[str, Any] | None) -> float | None:
    if not model:
        return None
    direct = _float_or_none(model.get("params_b"))
    if direct:
        return direct
    text = " ".join(str(model.get(key, "")) for key in ["name", "path"])
    match = re.search(r"(?i)(\d+(?:\.\d+)?)\s*b\b", text)
    if match:
        return float(match.group(1))
    size_bytes = _float_or_none(model.get("size_bytes"))
    quant = str(model.get("quant") or "").upper()
    if size_bytes:
        bits = 4.8
        if quant.startswith("Q5"):
            bits = 5.8
        elif quant.startswith("Q6"):
            bits = 6.8
        elif quant.startswith("Q8"):
            bits = 8.8
        elif quant in {"F16", "BF16"}:
            bits = 16.0
        elif quant == "F32":
            bits = 32.0
        return max((size_bytes * 8 / bits) / 1_000_000_000, 0.1)
    return None


def _model_size_mib(model: dict[str, Any] | None) -> float | None:
    size_bytes = _float_or_none((model or {}).get("size_bytes"))
    if size_bytes:
        return size_bytes / 1024 / 1024
    params_b = _model_params_b(model)
    quant = str((model or {}).get("quant") or "").upper()
    if not params_b:
        return None
    bits = 4.8
    if quant.startswith("Q5"):
        bits = 5.8
    elif quant.startswith("Q6"):
        bits = 6.8
    elif quant.startswith("Q8"):
        bits = 8.8
    elif quant in {"F16", "BF16"}:
        bits = 16.0
    elif quant == "F32":
        bits = 32.0
    return params_b * 1_000_000_000 * bits / 8 / 1024 / 1024


def _get_total_layers(model: dict[str, Any] | None) -> int | None:
    """Get the total number of layers from a model's GGUF file."""
    if not model:
        return None
    model_path = model.get("path") or model.get("model_path")
    if not model_path:
        return None
    # Check if we already have layer info cached
    if "n_layer" in model:
        return model.get("n_layer")
    return _read_gguf_n_layer(str(model_path))


def _quant_factor(model: dict[str, Any] | None, params: dict[str, Any]) -> float:
    quant = str((model or {}).get("quant") or "").upper()
    if not quant:
        cache = f"{params.get('cache_type_k', '')} {params.get('cache_type_v', '')}".upper()
        quant = cache
    for key, factor in QUANT_FACTORS.items():
        if key in quant:
            return factor
    return 0.92


def _gpu_factor(gpu_name: str) -> float:
    name = gpu_name.lower()
    if "5090" in name:
        return 1.2
    if "4090" in name or "6000" in name:
        return 1.0
    if "4080" in name or "3090" in name:
        return 0.76
    if "4070" in name or "3080" in name:
        return 0.58
    if "4060" in name or "3070" in name:
        return 0.43
    if "nvidia" in name or "rtx" in name:
        return 0.5
    if "radeon" in name or "amd" in name:
        return 0.36
    if "arc" in name or "intel" in name:
        return 0.28
    return 0.32


def _layer_fraction(params: dict[str, Any], model: dict[str, Any] | None = None) -> float:
    layers = params.get("gpu_layers", 999)
    if str(layers).lower() in {"all", "auto"}:
        return 1.0
    try:
        count = int(float(layers))
    except (TypeError, ValueError):
        return 1.0
    if count >= 999:
        return 1.0
    # Get actual layer count from GGUF file if available
    total_layers = _get_total_layers(model)
    if total_layers is not None and total_layers > 0:
        return max(0.0, min(1.0, count / total_layers))
    return max(0.0, min(1.0, count / 80))


def _cache_bytes(cache_type: Any) -> float:
    value = str(cache_type or "f16").upper()
    for key, bytes_per_value in CACHE_BYTES.items():
        if value == key or value.startswith(key):
            return bytes_per_value
    if value.startswith("Q8"):
        return 1.06
    if value.startswith("Q6"):
        return 0.78
    if value.startswith("Q5"):
        return 0.68
    if value.startswith("Q4") or value.startswith("IQ4"):
        return 0.53
    return 2.0


def _mib(value: float | int | None) -> float | None:
    if value is None:
        return None
    return float(value) / 1024 / 1024


def _round_mib(value: float | None) -> int | None:
    if value is None:
        return None
    return int(round(value))


def _status_from_headroom(headroom_mib: float | None, capacity_mib: float | None, target_mib: float) -> str:
    if headroom_mib is None or capacity_mib is None or capacity_mib <= 0:
        return "unknown"
    if headroom_mib >= max(target_mib, capacity_mib * 0.12):
        return "good"
    if headroom_mib >= max(512.0, target_mib * 0.5):
        return "tight"
    return "near_limit"


def _worst_status(statuses: list[str]) -> str:
    order = {"unknown": 0, "good": 1, "tight": 2, "near_limit": 3}
    if not statuses:
        return "unknown"
    return max(statuses, key=lambda status: order.get(status, 0))


def _status_label(status: str) -> str:
    return {
        "good": "Good",
        "tight": "Tight",
        "near_limit": "Near Limit",
        "unknown": "Unknown",
    }.get(status, "Unknown")


def estimate_memory_fit(
    params: dict[str, Any],
    model: dict[str, Any] | None = None,
    hardware: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate accelerator and RAM pressure for fit badges and live settings."""

    hardware = hardware or {}
    model_size_mib = _model_size_mib(model) or 0.0
    params_b = _model_params_b(model) or 13.0
    ctx = _float_or_none(params.get("ctx_size")) or 4096.0
    batch = _float_or_none(params.get("batch_size")) or 512.0
    ubatch = _float_or_none(params.get("ubatch_size")) or min(batch, 512.0)
    layer_fraction = _layer_fraction(params, model)
    kv_offload = bool(params.get("kv_offload", True))
    op_offload = bool(params.get("op_offload", True))
    mmap = bool(params.get("mmap", True))
    target_mib = _float_or_none(params.get("fit_target_mib")) or _float_or_none(params.get("target_mib")) or 1024.0

    cache_k = _cache_bytes(params.get("cache_type_k"))
    cache_v = _cache_bytes(params.get("cache_type_v"))
    avg_cache = (cache_k + cache_v) / 2.0
    kv_cache_mib = ctx * params_b * avg_cache * 0.0004
    compute_mib = 420.0 + min(batch, 4096.0) * 0.28 + min(ubatch, 2048.0) * 0.18
    if params.get("flash_attn", True):
        compute_mib *= 0.86
    compute_mib += min(ctx, 262144.0) / 262144.0 * 320.0

    accelerator_model_mib = model_size_mib * layer_fraction * 1.035
    host_model_mib = model_size_mib * (1.0 - layer_fraction) * 1.05
    if not mmap and model_size_mib:
        host_model_mib += model_size_mib * 0.35

    accelerator_used_mib = 0.0
    if layer_fraction > 0:
        accelerator_used_mib += accelerator_model_mib
    if kv_offload and layer_fraction > 0:
        accelerator_used_mib += kv_cache_mib
    if op_offload and layer_fraction > 0:
        accelerator_used_mib += compute_mib
    elif layer_fraction > 0:
        accelerator_used_mib += compute_mib * 0.35

    host_used_mib = host_model_mib
    if not kv_offload or layer_fraction <= 0:
        host_used_mib += kv_cache_mib
    if not op_offload:
        host_used_mib += compute_mib * 0.35

    primary_gpu = hardware.get("primary_gpu") or {}
    memory = hardware.get("memory") or {}
    unified_memory = bool(memory.get("unified") or primary_gpu.get("unified_memory"))
    accelerator_capacity_mib = _mib(primary_gpu.get("vram_free_bytes") or primary_gpu.get("vram_total_bytes"))
    if unified_memory and not accelerator_capacity_mib:
        accelerator_capacity_mib = _mib(memory.get("available_bytes") or memory.get("total_bytes"))
    ram_capacity_mib = _mib(memory.get("available_bytes") or memory.get("total_bytes"))

    accelerator_headroom_mib = (
        accelerator_capacity_mib - accelerator_used_mib if accelerator_capacity_mib is not None else None
    )
    ram_headroom_mib = ram_capacity_mib - host_used_mib if ram_capacity_mib is not None else None

    accelerator_status = _status_from_headroom(accelerator_headroom_mib, accelerator_capacity_mib, target_mib)
    ram_status = _status_from_headroom(ram_headroom_mib, ram_capacity_mib, max(2048.0, target_mib))
    relevant = [accelerator_status]
    if host_used_mib > 512 or not kv_offload or layer_fraction < 1.0:
        relevant.append(ram_status)
    status = _worst_status(relevant)

    accelerator_name = primary_gpu.get("name") or ("Unified memory" if unified_memory else "Accelerator")
    warnings: list[str] = []
    if not model:
        warnings.append("No matched model was available; fit estimate uses generic model assumptions.")
    if not accelerator_capacity_mib and layer_fraction > 0:
        warnings.append("Accelerator memory capacity is unknown, so the fit badge is approximate.")
    if host_used_mib > 512 and ram_capacity_mib is None:
        warnings.append("Host RAM capacity is unknown, so CPU/offload pressure is not fully checked.")

    return {
        "status": status,
        "label": _status_label(status),
        "accelerator_status": accelerator_status,
        "ram_status": ram_status,
        "accelerator_name": accelerator_name,
        "backend": primary_gpu.get("acceleration_backend") or primary_gpu.get("backend"),
        "uses_ram_offload": host_used_mib > 512 or not kv_offload or layer_fraction < 1.0,
        "model_size_mib": _round_mib(model_size_mib) or None,
        "estimated": {
            "accelerator_used_mib": _round_mib(accelerator_used_mib),
            "accelerator_capacity_mib": _round_mib(accelerator_capacity_mib),
            "accelerator_headroom_mib": _round_mib(accelerator_headroom_mib),
            "ram_used_mib": _round_mib(host_used_mib),
            "ram_capacity_mib": _round_mib(ram_capacity_mib),
            "ram_headroom_mib": _round_mib(ram_headroom_mib),
            "kv_cache_mib": _round_mib(kv_cache_mib),
            "compute_mib": _round_mib(compute_mib),
            "target_headroom_mib": _round_mib(target_mib),
        },
        "inputs": {
            "ctx_size": int(ctx),
            "gpu_layer_fraction": round(layer_fraction, 2),
            "cache_type_k": params.get("cache_type_k"),
            "cache_type_v": params.get("cache_type_v"),
            "kv_offload": kv_offload,
            "op_offload": op_offload,
        },
        "warnings": warnings,
    }


def enrich_profiles_with_fit_status(
    profiles: list[dict[str, Any]],
    hardware: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for profile in profiles:
        item = dict(profile)
        item["fit_status"] = estimate_memory_fit(item.get("params") or {}, item.get("model"), hardware)
        enriched.append(item)
    return enriched


def estimate_tokens_per_second(
    params: dict[str, Any],
    model: dict[str, Any] | None = None,
    hardware: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a decode-speed estimate calibrated with hardware bandwidth data."""

    hardware = hardware or {}
    model_params_b = _model_params_b(model) or 13.0
    primary_gpu = hardware.get("primary_gpu") or {}
    gpu_name = str(primary_gpu.get("name") or "")
    logical_cores = (hardware.get("cpu") or {}).get("logical_cores") or 8
    backend = str(primary_gpu.get("acceleration_backend") or primary_gpu.get("backend") or "")
    selected_backend = str(params.get("acceleration_backend") or "").lower()
    gpu_factor = _gpu_factor(gpu_name)
    if "metal" in backend.lower() or selected_backend == "metal":
        gpu_factor = max(gpu_factor, 0.64)
    elif selected_backend in {"vulkan", "hip", "rocm"}:
        gpu_factor = max(gpu_factor, 0.38)
    elif selected_backend == "sycl":
        gpu_factor = max(gpu_factor, 0.3)
    elif selected_backend == "cpu":
        gpu_factor = 0.0
    quant_factor = _quant_factor(model, params)
    layer_fraction = 0.0 if selected_backend == "cpu" else _layer_fraction(params, model)

    gpu_bandwidth_gbps = primary_gpu.get("vram_bandwidth_gbps")
    ram_bandwidth_gbps = (hardware.get("memory") or {}).get("ram_bandwidth_gbps")
    has_bandwidth_info = gpu_bandwidth_gbps is not None or ram_bandwidth_gbps is not None

    gpu_decode = 1140 * gpu_factor * quant_factor / math.sqrt(max(model_params_b, 0.5))
    cpu_decode = max(1.2, 9.0 * math.sqrt(max(float(logical_cores), 1.0)) / math.sqrt(max(model_params_b, 1.0)))
    blended = gpu_decode * (layer_fraction**1.35) + cpu_decode * (1.0 - layer_fraction)

    ctx = _float_or_none(params.get("ctx_size")) or 4096
    ctx_factor = max(0.72, 1.0 - min(ctx, 262144) / 262144 * 0.18)
    batch = _float_or_none(params.get("batch_size")) or 512
    ubatch = _float_or_none(params.get("ubatch_size")) or 512
    batch_factor = 1.0 + min(max(batch, 1), 2048) / 2048 * 0.05
    if ubatch < 256:
        batch_factor *= 0.92
    if params.get("flash_attn", True) and ctx >= 8192:
        batch_factor *= 1.06
    if not params.get("kv_offload", True) and layer_fraction > 0.5:
        batch_factor *= 0.74
    if not params.get("op_offload", True) and layer_fraction > 0.25:
        batch_factor *= 0.9
    if params.get("draft_model") and str(params.get("spec_type", "")).strip():
        batch_factor *= 1.08

    # Memory bandwidth is a hard ceiling on decode speed: a token cannot be
    # produced faster than the weights it reads can be streamed. Apply it as a
    # cap (min), never a boost, and only trust "high" confidence when the cap
    # actually binds — having the numbers present is not the same as using them.
    bandwidth_bound = False
    if layer_fraction >= 1.0 and gpu_bandwidth_gbps and gpu_bandwidth_gbps > 0:
        ceiling = _estimate_gpu_gpu_speed(gpu_bandwidth_gbps, gpu_name, model_params_b, quant_factor, layer_fraction)
        if ceiling > 0 and ceiling < blended:
            blended = ceiling
            bandwidth_bound = True
    if layer_fraction < 1.0 and ram_bandwidth_gbps and ram_bandwidth_gbps > 0:
        ceiling = _estimate_ram_spill_speed(ram_bandwidth_gbps, model_params_b, layer_fraction)
        if ceiling > 0 and ceiling < blended:
            blended = ceiling
            bandwidth_bound = True

    estimate = max(0.5, blended * ctx_factor * batch_factor)
    if bandwidth_bound and model:
        confidence = "high"
    elif model and primary_gpu:
        confidence = "medium"
    else:
        confidence = "low"
    low = estimate * (0.82 if confidence == "high" else 0.72 if confidence == "medium" else 0.55)
    high = estimate * (1.18 if confidence == "high" else 1.28 if confidence == "medium" else 1.55)

    assumptions = [
        "Estimate is for decode speed after the prompt is processed.",
        "Real speed depends on the exact llama.cpp build, prompt shape, and background load.",
    ]
    if has_bandwidth_info:
        if gpu_bandwidth_gbps:
            assumptions.append(f"GPU VRAM bandwidth detected: {gpu_bandwidth_gbps} GB/s.")
        if ram_bandwidth_gbps:
            assumptions.append(f"System RAM bandwidth detected: {ram_bandwidth_gbps} GB/s.")
    if bandwidth_bound:
        assumptions.append("Estimate is capped by measured memory bandwidth (decode is bandwidth-bound).")
    if layer_fraction < 1:
        assumptions.append("Partial GPU layers usually means more system RAM traffic and lower speed.")
    if not params.get("kv_offload", True):
        assumptions.append("KV cache offload is disabled, so long contexts may run slower.")

    return {
        "estimate_tps": round(estimate, 1),
        "low_tps": round(low, 1),
        "high_tps": round(high, 1),
        "confidence": confidence,
        "model_params_b": round(model_params_b, 2),
        "gpu_name": gpu_name or None,
        "gpu_layer_fraction": round(layer_fraction, 2),
        "assumptions": assumptions,
    }


def _estimate_gpu_gpu_speed(gpu_bandwidth_gbps: float, gpu_name: str, model_params_b: float, quant_factor: float, layer_fraction: float) -> float:
    """Estimate TPS based on GPU memory bandwidth bound."""
    if model_params_b <= 0:
        return 0.0
    model_size_mib = model_params_b * 1e9 * 4.8 / 8 / 1024 / 1024
    
    gpu_bw = gpu_bandwidth_gbps
    if "4090" in gpu_name.lower():
        gpu_bw = min(gpu_bw, 1000)
    elif "3090" in gpu_name.lower():
        gpu_bw = min(gpu_bw, 600)
    elif "4080" in gpu_name.lower():
        gpu_bw = min(gpu_bw, 450)
    elif "4070" in gpu_name.lower():
        gpu_bw = min(gpu_bw, 350)
    
    # gpu_bw is GB/s; bytes/s / bytes-per-token -> tokens/s
    tps = (gpu_bw * 1000) / (model_size_mib * 1024 * 1024 / 1e6) * quant_factor * layer_fraction
    tps = min(tps, gpu_bw / model_params_b * 500 * quant_factor)
    return max(tps, 1.0)


def _estimate_ram_spill_speed(ram_bandwidth_gbps: float, model_params_b: float, layer_fraction: float) -> float:
    """RAM-bandwidth ceiling on TPS when part of the model spills to system RAM.

    ram_bandwidth_gbps is GB/s (bytes). Each token must stream the spilled
    fraction of the weights through host RAM (the slow path that dominates),
    so tps_ceiling = (RAM bytes/s) / (spilled model bytes per token). Weight
    size assumes ~4.8 bits/param (Q4-class), matching _estimate_gpu_gpu_speed.
    """
    if ram_bandwidth_gbps <= 0 or model_params_b <= 0:
        return 0.0
    spill_fraction = max(1.0 - layer_fraction, 0.0)
    if spill_fraction <= 0:
        return 0.0
    spilled_bytes_per_token = model_params_b * 1e9 * 4.8 / 8 * spill_fraction
    ram_bytes_per_s = ram_bandwidth_gbps * 1e9
    return max(ram_bytes_per_s / spilled_bytes_per_token, 0.3)
