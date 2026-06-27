from __future__ import annotations

from typing import Any, Callable

from .estimates import estimate_memory_fit, estimate_tokens_per_second, _get_total_layers, prime_model_meta

# ponytail: greedy grid scan over the existing estimator (layers x ctx x kv-cache).
# No subprocess, no optimizer lib — ~100 cheap pure-Python fit evals. The ceiling
# is the estimator's own accuracy; a real benchmark should override these picks.
CTX_LADDER = [2048, 4096, 8192, 16384, 32768, 49152, 65536, 98304, 131072]
CACHE_LADDER = ["f16", "q8_0", "q5_1", "q4_0"]  # highest quality -> most compact
# higher rank == better KV quality, used to weight/break ties toward fidelity
_CACHE_RANK = {name: i for i, name in enumerate(reversed(CACHE_LADDER))}
_MAX_CACHE_RANK = max(_CACHE_RANK.values())
_MAX_CTX_INDEX = len(CTX_LADDER) - 1

# K and V are tuned independently. The K cache is more sensitive to quantization
# than V, so we (a) never spend more bits on V than K and (b) weight K fidelity
# higher when scoring. This makes asymmetric picks like q8_0 K / q4_0 V a memory
# win that keeps the precision that matters most.
_CACHE_K_WEIGHT = 0.6
_CACHE_V_WEIGHT = 0.4


def _cache_fidelity_norm(cache_k: str, cache_v: str) -> float:
    rank_k = _CACHE_RANK.get(cache_k, 0)
    rank_v = _CACHE_RANK.get(cache_v, 0)
    return (_CACHE_K_WEIGHT * rank_k + _CACHE_V_WEIGHT * rank_v) / _MAX_CACHE_RANK

# The balanced pick leans toward KV quality: quant fidelity is weighted slightly
# above context size, so the tuner won't trade a better cache quant for a bigger
# window — it grows context only once a sensible quant is locked in.
_BALANCED_CACHE_WEIGHT = 0.55
_BALANCED_CTX_WEIGHT = 0.45

_TUNE_KEYS = ("gpu_layers", "ctx_size", "cache_type_k", "cache_type_v")
_REASONS = {
    "gpu_layers": "offload as many layers to the accelerator as memory allows (biggest speed lever)",
    "ctx_size": "grow the context window into the remaining memory headroom",
    "cache_type_k": "pick the KV-cache quant that best balances fidelity and memory",
    "cache_type_v": "pick the KV-cache quant that best balances fidelity and memory",
    "flash_attn": "enable flash attention (required for a quantized KV cache)",
}

# Named intents the tuner reports so a caller can pick by current need.
_INTENTS = (
    ("balanced", "Balanced",
     "Best overall fit; leans toward KV-cache quality, then grows context."),
    ("max_quality", "Max quality",
     "Highest-fidelity KV cache that fits, then as much context as fits."),
    ("max_context", "Max context",
     "Largest context window that fits, then the best KV quant for it."),
)


def _layer_options(model: dict[str, Any] | None) -> list[Any]:
    total = _get_total_layers(model)
    if total and total > 0:
        return ["all", int(total * 0.75), int(total * 0.5), int(total * 0.25), 0]
    # Unknown layer count: only full-GPU or pure-CPU are reliable to estimate.
    return ["all", 0]


def _changes(base: dict[str, Any], tuned: dict[str, Any]) -> list[dict[str, Any]]:
    changes = []
    for key in (*_TUNE_KEYS, "flash_attn"):
        before, after = base.get(key), tuned.get(key)
        if str(before) != str(after):
            changes.append({"field": key, "from": before, "to": after, "why": _REASONS[key]})
    return changes


def _candidate_params(base: dict[str, Any], layers: Any, ctx: int, cache_k: str, cache_v: str) -> dict[str, Any]:
    cand = {**base, "gpu_layers": layers, "ctx_size": ctx,
            "cache_type_k": cache_k, "cache_type_v": cache_v}
    # Quantized KV requires flash attention in llama.cpp; force it on so the
    # suggested config can actually launch (and so the estimate reflects it).
    if cache_k != "f16" or cache_v != "f16":
        cand["flash_attn"] = True
    return cand


def _collect_candidates(
    base: dict[str, Any],
    model: dict[str, Any] | None,
    hardware: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Evaluate the grid once and keep every config the estimator says fits."""
    candidates: list[dict[str, Any]] = []
    for layers in _layer_options(model):
        for ctx in CTX_LADDER:
            for cache_k in CACHE_LADDER:
                for cache_v in CACHE_LADDER:
                    # Never spend more bits on V than K — K carries more signal.
                    if _CACHE_RANK[cache_v] > _CACHE_RANK[cache_k]:
                        continue
                    cand = _candidate_params(base, layers, ctx, cache_k, cache_v)
                    fit = estimate_memory_fit(cand, model, hardware)
                    if fit["status"] in ("near_limit", "unknown"):
                        continue
                    # Don't trust a GPU offload we can't size against real VRAM.
                    if fit["inputs"]["gpu_layer_fraction"] > 0 and fit["estimated"]["accelerator_capacity_mib"] is None:
                        continue
                    candidates.append({
                        "params": cand,
                        "fit": fit,
                        "cache_k": cache_k,
                        "cache_v": cache_v,
                        "lf": fit["inputs"]["gpu_layer_fraction"],
                        "ctx_norm": CTX_LADDER.index(ctx) / _MAX_CTX_INDEX,
                        "cache_norm": _cache_fidelity_norm(cache_k, cache_v),
                        "roomy": 1 if fit["status"] == "good" else 0,
                    })
    return candidates


# Each key maximizes GPU layers first (the dominant fit/speed lever), then the
# intent-specific trade-off between context and KV quant, then prefers the
# roomier (non-tight) fit as a final safety tiebreak.
_INTENT_KEYS: dict[str, Callable[[dict[str, Any]], tuple]] = {
    "balanced": lambda c: (
        c["lf"],
        _BALANCED_CACHE_WEIGHT * c["cache_norm"] + _BALANCED_CTX_WEIGHT * c["ctx_norm"],
        c["cache_norm"],  # tie toward fidelity
        c["roomy"],
    ),
    "max_quality": lambda c: (c["lf"], c["cache_norm"], c["ctx_norm"], c["roomy"]),
    "max_context": lambda c: (c["lf"], c["ctx_norm"], c["cache_norm"], c["roomy"]),
}


def _signature(cand: dict[str, Any]) -> tuple:
    p = cand["params"]
    return (str(p.get("gpu_layers")), p.get("ctx_size"), p.get("cache_type_k"), p.get("cache_type_v"))


def auto_tune_fit(
    params: dict[str, Any],
    model: dict[str, Any] | None = None,
    hardware: dict[str, Any] | None = None,
    target_mib: int = 1024,
) -> dict[str, Any]:
    """Search launch params for the best memory fit, by named intent.

    Maximizes GPU offload first (the biggest speed lever), then trades context
    against KV-cache fidelity. The default ("balanced") pick leans toward quant
    quality so it never drops to a worse KV quant just to enlarge the cache.
    Returns the balanced pick as ``tuned_params`` plus a ``suggestions`` list
    (balanced / max quality / max context) so a caller can choose by need.
    Rejects any candidate the estimator flags as near_limit or can't verify.
    """
    base = dict(params or {})
    base.setdefault("fit_target_mib", target_mib)
    # Parse the GGUF once up front so every grid eval below reads exact KV dims
    # from cache instead of re-opening the (slow) header.
    prime_model_meta(model)
    before_fit = estimate_memory_fit(base, model, hardware)
    before_speed = estimate_tokens_per_second(base, model, hardware)

    candidates = _collect_candidates(base, model, hardware)
    if not candidates:
        return {
            "success": False,
            "reason": "No configuration fit within memory, or accelerator capacity is unknown.",
            "before": {"params": base, "fit_status": before_fit, "speed_estimate": before_speed},
        }

    # Pick the best candidate per intent, de-duplicating identical configs and
    # merging the labels of any intent that lands on the same config.
    suggestions: list[dict[str, Any]] = []
    by_signature: dict[tuple, dict[str, Any]] = {}
    for intent_id, label, description in _INTENTS:
        best = max(candidates, key=_INTENT_KEYS[intent_id])
        sig = _signature(best)
        if sig in by_signature:
            entry = by_signature[sig]
            entry["intents"].append(intent_id)
            entry["labels"].append(label)
            entry["label"] = " / ".join(entry["labels"])
            continue
        tuned = best["params"]
        entry = {
            "intent": intent_id,
            "intents": [intent_id],
            "label": label,
            "labels": [label],
            "description": description,
            "params": tuned,
            "changes": _changes(base, tuned),
            "fit_status": best["fit"],
            "speed_estimate": estimate_tokens_per_second(tuned, model, hardware),
        }
        by_signature[sig] = entry
        suggestions.append(entry)

    primary = suggestions[0]  # balanced is listed first
    tuned, after_fit = primary["params"], primary["fit_status"]
    return {
        "success": True,
        "tuned_params": tuned,
        "changes": primary["changes"],
        "suggestions": suggestions,
        "before": {"params": base, "fit_status": before_fit, "speed_estimate": before_speed},
        "after": {"params": tuned, "fit_status": after_fit, "speed_estimate": primary["speed_estimate"]},
        "notes": [
            "Suggestions come from the memory estimator, not a live run — verify with a fit test or benchmark.",
            "Priority: max GPU layers, then a balance of KV-cache fidelity and context (quality-leaning).",
            "K and V caches are tuned independently; V is never set more precise than K.",
            "Pick 'Max quality' or 'Max context' from the suggestions when your need leans one way.",
        ],
    }


def demo() -> None:
    """ponytail self-check: tuning never recommends an overflowing config, a
    roomy GPU gets full offload, and quality/context intents are reported."""
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
    assert out["suggestions"], "expected named suggestions"

    # Max-context should never carry a higher-fidelity-but-smaller window than
    # max-quality, and max-quality should never use a more compact quant.
    quality = next((s for s in out["suggestions"] if "max_quality" in s["intents"]), None)
    context = next((s for s in out["suggestions"] if "max_context" in s["intents"]), None)
    if quality and context:
        assert context["params"]["ctx_size"] >= quality["params"]["ctx_size"]
        assert _CACHE_RANK[quality["params"]["cache_type_k"]] >= _CACHE_RANK[context["params"]["cache_type_k"]]

    # No suggestion may spend more bits on V than K.
    for s in out["suggestions"]:
        p = s["params"]
        assert _CACHE_RANK[p["cache_type_v"]] <= _CACHE_RANK[p["cache_type_k"]], p

    # Tiny VRAM with unknown capacity falls back to a safe pick or reports failure.
    tiny = {"primary_gpu": {}, "memory": {"total_bytes": 8 * 1024**3, "available_bytes": 2 * 1024**3},
            "cpu": {"logical_cores": 8}}
    out2 = auto_tune_fit({"gpu_layers": "all", "ctx_size": 131072}, model, tiny)
    if out2["success"]:
        assert out2["after"]["fit_status"]["status"] != "near_limit"
    print("smart_tune demo OK")


if __name__ == "__main__":
    demo()
