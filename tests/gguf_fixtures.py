"""Synthetic GGUF files for tests.

Real models are tens of gigabytes; these are a few kilobytes and carry only the
metadata and tensor names the extraction code reads.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import gguf


def write_minimal_gguf(
    path: Path,
    *,
    arch: str,
    n_layer: int,
    attn_layers: list[int],
    n_kv_heads: int,
    k_len: int,
    v_len: int,
    extra_kv: dict | None = None,
) -> Path:
    """Write a GGUF whose header says `arch`/`n_layer` and whose tensor list
    carries `attn_k.weight`/`attn_v.weight` only for the layers in `attn_layers`.

    `extra_kv` adds raw uint32 metadata keys (e.g. full_attention_interval),
    written under the `arch.` prefix.
    """
    writer = gguf.GGUFWriter(str(path), arch)
    writer.add_uint32(f"{arch}.block_count", n_layer)
    writer.add_uint32(f"{arch}.attention.head_count", n_kv_heads * 8)
    writer.add_uint32(f"{arch}.attention.head_count_kv", n_kv_heads)
    writer.add_uint32(f"{arch}.attention.key_length", k_len)
    writer.add_uint32(f"{arch}.attention.value_length", v_len)
    writer.add_uint32(f"{arch}.embedding_length", 2048)
    writer.add_uint32(f"{arch}.context_length", 4096)
    for key, value in (extra_kv or {}).items():
        writer.add_uint32(f"{arch}.{key}", value)

    tiny = np.zeros((2, 2), dtype=np.float32)
    for idx in attn_layers:
        writer.add_tensor(f"blk.{idx}.attn_k.weight", tiny)
        writer.add_tensor(f"blk.{idx}.attn_v.weight", tiny)

    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    writer.write_tensors_to_file()
    writer.close()
    return path
