"""Run the truth layer beside the legacy estimator and log disagreement.

Surfaces nothing. Its only job is to accumulate evidence about whether the
truth layer is ready to replace the estimator, and on which models they differ.

Every entry point swallows exceptions: shadow mode observes the fit path and
must never be able to break it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import estimates
from ..paths import cache_dir
from .gguf import read_facts
from .kv import breakdown

_LOG_FILENAME = "kv_divergence.jsonl"


def _log_path() -> Path:
    return cache_dir() / _LOG_FILENAME


def record_divergence(model_path: str | None, params: dict[str, Any],
                      legacy_kv_mib: float | None) -> dict[str, Any] | None:
    """Compare the legacy KV figure against the truth layer and append a record.

    ``delta_pct`` is ``(legacy - truth) / truth * 100``: positive means the
    legacy estimator reads *higher* than the truth layer, negative means it
    reads lower.

    Returns the comparison, or None if it could not be made. Never raises.
    """
    if not model_path or legacy_kv_mib is None:
        return None
    try:
        facts = read_facts(model_path)
        ctx = int(params.get("ctx_size") or 4096)
        ctk = params.get("cache_type_k") or "f16"
        ctv = params.get("cache_type_v") or "f16"
        result = breakdown(
            facts,
            weights_bytes=0,
            ctx=ctx,
            ctk=ctk,
            ctv=ctv,
        )
        if result.kv_bytes is None:
            return None
        truth_mib = result.kv_bytes / 1024 / 1024
        delta_pct = ((legacy_kv_mib - truth_mib) / truth_mib * 100) if truth_mib else 0.0
        # Whether the legacy figure came from exact GGUF dims already resolved
        # (memory or on-disk cache hit) rather than the KV_FALLBACK_FACTOR
        # heuristic guess -- probe=False so this never triggers a parse of its
        # own, it only reports what legacy already knows. A large divergence
        # with legacy_exact False is a wild guess, not a formula disagreement.
        legacy_exact = estimates._kv_dims({"path": model_path}, probe=False) is not None
        entry = {
            "model": Path(model_path).name,
            "arch": facts.arch,
            "source": facts.source,
            "n_layers": facts.n_layers,
            "n_attn_layers": facts.n_attn_layers,
            "ctx": ctx,
            "ctk": str(ctk),
            "ctv": str(ctv),
            "legacy_kv_mib": round(legacy_kv_mib, 2),
            "truth_kv_mib": round(truth_mib, 2),
            "delta_pct": round(delta_pct, 2),
            "legacy_exact": legacy_exact,
        }
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        return entry
    except Exception:
        return None
