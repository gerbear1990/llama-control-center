from __future__ import annotations

from typing import Any

from .estimates import estimate_memory_fit, estimate_tokens_per_second, _get_total_layers

# ponytail: greedy grid scan over the existing estimator (layers x ctx x kv-cache).
# No subprocess, no optimizer lib — ~100 cheap pure-Python fit evals. The ceiling
# is the estimator's own accuracy; a real benchmark should override these picks.
CTX_LADDER = [2048, 4096, 8192, 16384, 32768, 49152, 65536, 98304, 131072]
CACHE_LADDER = ["f16", "q8_0", "q5_1", "q4_0"]  # highest quality -> most compact
# higher rank == better KV quality, used to break ties toward fidelity
_CACHE_RANK = {name: i for i, name in enumerate(reversed(CACHE_LADDER))}

_TUNE_KEYS = ("gpu_layers", "ctx_size", "cache_type_k", "cache_type_v")
_REASONS = {
    "gpu_layers": "offload as many layers to the accelerator as memory allows (biggest speed lever)",
    "ctx_size": "grow the context window into the remaining memory headroom",
    "cache_type_k": "use a more compact KV cache to make room for context",
    "cache_type_v": "use a more compact KV cache to make room for context",
}


def _layer_options(model: dict[str, Any] | None) -> list[Any]:
    total = _get_total_layers(model)
    if total and total > 0:
        return ["all", int(total * 0.75), int(total * 0.5), int(total * 0.25), 0]
    # Unknown layer count: only full-GPU or pure-CPU are reliable to estimate.
    return ["all", 0]


def _changes(base: dict[str, Any], tuned: dict[str, Any]) -> list[dict[str, Any]]:
    changes = []
    for key in _TUNE_KEYS:
        before, after = base.get(key), tuned.get(key)
        if str(before) != str(after):
            changes.append({"field": key, "from": before, "to": after, "why": _REASONS[key]})
    return changes


def auto_tune_fit(
    params: dict[str, Any],
    model: dict[str, Any] | None = None,
    hardware: dict[str, Any] | None = None,
    target_mib: int = 1024,
) -> dict[str, Any]:
    """Search launch params for the highest memory utilization that still fits.

    Prefers, in order: more GPU layers (speed), larger context, higher KV-cache
    fidelity, then tighter memory use. Rejects any candidate the estimator flags
    as near_limit (overflow risk) or can't verify.
    """
    base = dict(params or {})
    base.setdefault("fit_target_mib", target_mib)
    before_fit = estimate_memory_fit(base, model, hardware)
    before_speed = estimate_tokens_per_second(base, model, hardware)

    best = None  # (score_tuple, candidate, fit)
    for layers in _layer_options(model):
        for ctx in CTX_LADDER:
            for cache in CACHE_LADDER:
                cand = {**base, "gpu_layers": layers, "ctx_size": ctx,
                        "cache_type_k": cache, "cache_type_v": cache}
                fit = estimate_memory_fit(cand, model, hardware)
                if fit["status"] in ("near_limit", "unknown"):
                    continue
                # Don't trust a GPU offload we can't size against real VRAM.
                if fit["inputs"]["gpu_layer_fraction"] > 0 and fit["estimated"]["accelerator_capacity_mib"] is None:
                    continue
                score = (
                    fit["inputs"]["gpu_layer_fraction"],
                    fit["inputs"]["ctx_size"],
                    _CACHE_RANK.get(cache, 0),
                    1 if fit["status"] == "tight" else 0,
                )
                if best is None or score > best[0]:
                    best = (score, cand, fit)

    if best is None:
        return {
            "success": False,
            "reason": "No configuration fit within memory, or accelerator capacity is unknown.",
            "before": {"params": base, "fit_status": before_fit, "speed_estimate": before_speed},
        }

    _, tuned, after_fit = best
    after_speed = estimate_tokens_per_second(tuned, model, hardware)
    return {
        "success": True,
        "tuned_params": tuned,
        "changes": _changes(base, tuned),
        "before": {"params": base, "fit_status": before_fit, "speed_estimate": before_speed},
        "after": {"params": tuned, "fit_status": after_fit, "speed_estimate": after_speed},
        "notes": [
            "Suggestions come from the memory estimator, not a live run — verify with a fit test or benchmark.",
            "Priority: max GPU layers, then larger context, then higher KV-cache fidelity.",
        ],
    }


def demo() -> None:
    """ponytail self-check: tuning never recommends an overflowing config, and
    a roomy GPU gets full offload."""
    model = {"name": "test-7B", "params_b": 7, "quant": "Q4_K_M"}
    hw = {
        "primary_gpu": {"name": "RTX 4090", "vram_total_bytes": 24 * 1024**3,
                        "vram_free_bytes": 24 * 1024**3, "vram_bandwidth_gbps": 1000},
        "memory": {"total_bytes": 64 * 1024**3, "available_bytes": 48 * 1024**3},
        "cpu": {"logical_cores": 16},
    }
    out = auto_tune_fit({"gpu_layers": 0, "ctx_size": 2048, "cache_type_k": "q4_0",
                         "cache_type_v": "q4_0"}, model, hw)
    assert out["success"], out
    assert out["after"]["fit_status"]["status"] != "near_limit"
    assert str(out["tuned_params"]["gpu_layers"]) == "all", out["tuned_params"]
    assert out["after"]["fit_status"]["inputs"]["ctx_size"] >= 2048

    # Tiny VRAM with unknown capacity falls back to a safe pick or reports failure.
    tiny = {"primary_gpu": {}, "memory": {"total_bytes": 8 * 1024**3, "available_bytes": 2 * 1024**3},
            "cpu": {"logical_cores": 8}}
    out2 = auto_tune_fit({"gpu_layers": "all", "ctx_size": 131072}, model, tiny)
    if out2["success"]:
        assert out2["after"]["fit_status"]["status"] != "near_limit"
    print("smart_tune demo OK")


if __name__ == "__main__":
    demo()
