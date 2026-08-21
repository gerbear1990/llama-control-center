"""Memory arithmetic over ArchFacts. Pure: no I/O, no globals, no clock.

Purity is the point. Every figure this module produces is arithmetic over
metadata read from the model file, so it can be checked exhaustively in tests
and, later, against what llama.cpp actually allocates.
"""
from __future__ import annotations

from dataclasses import dataclass

from .gguf import ArchFacts

# Bytes per stored element by KV cache type. Quantized types carry block scales,
# so q8_0 is 8.5 bits (1.0625 B), not 1.0.
CACHE_BYTES: dict[str, float] = {
    "F32": 4.0, "F16": 2.0, "BF16": 2.0,
    "Q8_0": 1.0625,
    "Q5_1": 0.75, "Q5_0": 0.6875,
    "Q4_1": 0.5625, "Q4_0": 0.5,
    "IQ4_NL": 0.5625,
}

_FALLBACK_BYTES = 2.0  # unknown type: assume f16 rather than guess smaller


def cache_bytes_per_elem(name: str | None) -> float:
    """Bytes per element for a llama.cpp KV cache type (``-ctk`` / ``-ctv``)."""
    key = str(name or "f16").upper()
    if key in CACHE_BYTES:
        return CACHE_BYTES[key]
    for prefix, value in (("Q8", 1.0625), ("Q6", 0.8125), ("Q5", 0.75),
                          ("IQ4", 0.5625), ("Q4", 0.5625)):
        if key.startswith(prefix):
            return value
    return _FALLBACK_BYTES


def kv_bytes_per_token(facts: ArchFacts, ctk: str | None = "f16",
                       ctv: str | None = "f16") -> int | None:
    """Bytes of KV cache added by one token, across all attention layers.

    ``facts.total_kv_heads`` already folds in the attention-layer count, so it
    must not be multiplied by a layer count again.
    """
    if facts.total_kv_heads is None or facts.k_len is None or facts.v_len is None:
        return None
    per_token = (
        facts.total_kv_heads * facts.k_len * cache_bytes_per_elem(ctk)
        + facts.total_kv_heads * facts.v_len * cache_bytes_per_elem(ctv)
    )
    return int(round(per_token))


def ssm_state_bytes(facts: ArchFacts) -> int:
    """Recurrent state held by SSM layers. Constant in context length.

    Per layer: a convolution window of ``inner_size x (conv_kernel - 1)`` plus a
    recurrent state of ``inner_size x state_size``, both f32.
    """
    if not facts.is_hybrid or not facts.ssm_inner_size:
        return 0
    conv = facts.ssm_inner_size * max(0, (facts.ssm_conv_kernel or 1) - 1)
    state = facts.ssm_inner_size * (facts.ssm_state_size or 0)
    return (conv + state) * 4 * facts.n_ssm_layers


@dataclass(frozen=True)
class Breakdown:
    weights_bytes: int
    mmproj_bytes: int
    kv_bytes: int | None
    ssm_bytes: int
    total_bytes: int | None
    kv_bytes_per_token: int | None
    provenance: str  # "computed" | "unknown"


def breakdown(facts: ArchFacts, *, weights_bytes: int, ctx: int,
              ctk: str | None = "f16", ctv: str | None = "f16",
              mmproj_bytes: int = 0) -> Breakdown:
    """Total resident bytes for a given model and launch configuration.

    Excludes the compute buffer, which depends on batch size and backend and is
    measured rather than predicted.
    """
    per_token = kv_bytes_per_token(facts, ctk, ctv)
    ssm = ssm_state_bytes(facts)
    if per_token is None:
        return Breakdown(weights_bytes, mmproj_bytes, None, ssm, None, None, "unknown")
    kv_bytes = per_token * int(ctx)
    total = weights_bytes + mmproj_bytes + kv_bytes + ssm
    return Breakdown(weights_bytes, mmproj_bytes, kv_bytes, ssm, total,
                     per_token, "computed")
