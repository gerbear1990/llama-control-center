"""Typed architecture facts read from a GGUF header.

This wraps the ``gguf`` package rather than parsing bytes: ``GGUFReader`` is
already a project dependency and already used by ``estimates``. What this module
adds is a typed surface, a single tested code path, and explicit provenance for
how the attention-layer count was determined.
"""
from __future__ import annotations

import io
import os
import re
import struct
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import gguf

# Layer-index patterns in tensor names. Must recognise the same set as
# estimates._N_LAYER_PATTERNS so the two implementations never disagree about
# which architectures have a discoverable attention-layer count: blk.N,
# block.N, model.layers.N / transformer.layer.N, and .h[N]. (transformer.layer
# and model.layers both match the trailing `layers?\.` alternative here.)
_LAYER_RE = re.compile(r"\.h\[(\d+)\]\.|blk\.(\d+)\.|block\.(\d+)\.|layers?\.(\d+)\.")

_ATTN_SUFFIXES = (".attn_k.weight", ".attn_v.weight")
_ATTN_SUBSTRINGS = (".k_proj.", ".v_proj.", "attn_k", "attn_v")


@dataclass(frozen=True)
class ArchFacts:
    """What a GGUF header says about a model's memory-relevant structure.

    ``total_kv_heads`` is already summed across attention layers — multiplying
    it by a layer count again is a double-count. This mirrors the convention in
    ``estimates._kv_head_total``, which handles both scalar GQA and the
    per-layer arrays used by mixed local/global attention (e.g. Gemma).
    """

    arch: str | None
    n_layers: int | None
    attn_layer_indices: tuple[int, ...]
    total_kv_heads: int | None
    k_len: int | None
    v_len: int | None
    native_ctx: int | None
    n_experts: int
    n_experts_used: int
    has_mtp: bool
    needs_mmproj: bool
    ssm_conv_kernel: int | None
    ssm_state_size: int | None
    ssm_inner_size: int | None
    ssm_group_count: int | None
    source: str  # "tensor-scan" | "interval-metadata" | "assumed-dense"

    @property
    def n_attn_layers(self) -> int:
        return len(self.attn_layer_indices)

    @property
    def n_ssm_layers(self) -> int:
        if self.n_layers is None:
            return 0
        return max(0, self.n_layers - self.n_attn_layers)

    @property
    def is_hybrid(self) -> bool:
        return self.n_ssm_layers > 0

    @property
    def is_moe(self) -> bool:
        return self.n_experts > 0


def _int(meta: dict, key: str) -> int | None:
    value = meta.get(key)
    return value if isinstance(value, int) and value > 0 else None


def _layer_index(name: str) -> int | None:
    """Extract the transformer-layer index from a tensor name, or None.

    ``_LAYER_RE`` has one capture group per alternative, so exactly one group
    binds on a match -- return the first that did (mirrors
    ``estimates._layer_index_from_tensor``).
    """
    match = _LAYER_RE.search(name)
    if not match:
        return None
    for group in match.groups():
        if group is not None:
            return int(group)
    return None


def _is_attn_tensor(name: str) -> bool:
    if name.endswith(_ATTN_SUFFIXES):
        return True
    return any(token in name for token in _ATTN_SUBSTRINGS)


def _kv_heads_total(meta: dict, arch: str, n_attn: int) -> int | None:
    """Sum KV heads across attention layers.

    ``head_count_kv`` is a scalar for plain GQA and a per-layer array for mixed
    local/global attention (e.g. Gemma). An array is summed as-is; a scalar is
    multiplied by the attention-layer count.
    """
    value = meta.get(f"{arch}.attention.head_count_kv")
    if isinstance(value, (list, tuple)):
        total = sum(int(v) for v in value if int(v) > 0)
        return total or None
    if not isinstance(value, int) or value <= 0:
        value = _int(meta, f"{arch}.attention.head_count")
    if isinstance(value, int) and value > 0 and n_attn > 0:
        return value * n_attn
    return None


def _facts_from_kv_and_tensors(meta: dict, tensor_names: list[str]) -> ArchFacts:
    """Build ArchFacts from a metadata mapping and a list of tensor names.

    Both the local (``GGUFReader``) and remote (range-request) paths funnel
    through here, so the two cannot drift apart.
    """
    arch = meta.get("general.architecture")
    arch = arch if isinstance(arch, str) and arch else None

    n_layers = _int(meta, f"{arch}.block_count") if arch else None

    attn: set[int] = set()
    has_mtp = False
    needs_mmproj = False
    for name in tensor_names:
        if "nextn" in name or ".mtp." in name:
            has_mtp = True
        if "mrope" in name or "vision" in name:
            needs_mmproj = True
        if _is_attn_tensor(name):
            idx = _layer_index(name)
            if idx is not None:
                attn.add(idx)

    if arch and meta.get(f"{arch}.rope.dimension_sections") is not None:
        needs_mmproj = True

    source = "tensor-scan"
    if not attn and arch and n_layers:
        interval = _int(meta, f"{arch}.full_attention_interval")
        if interval and interval > 1:
            attn = set(range(interval - 1, n_layers, interval))
            source = "interval-metadata"
        else:
            attn = set(range(n_layers))
            source = "assumed-dense"

    indices = tuple(sorted(attn))
    n_attn = len(indices)

    k_len = _int(meta, f"{arch}.attention.key_length") if arch else None
    v_len = _int(meta, f"{arch}.attention.value_length") if arch else None
    if arch and (k_len is None or v_len is None):
        n_embd = _int(meta, f"{arch}.embedding_length")
        n_head = _int(meta, f"{arch}.attention.head_count")
        head_dim = n_embd // n_head if n_embd and n_head else None
        k_len = k_len or head_dim
        v_len = v_len or head_dim

    return ArchFacts(
        arch=arch,
        n_layers=n_layers,
        attn_layer_indices=indices,
        total_kv_heads=_kv_heads_total(meta, arch, n_attn) if arch else None,
        k_len=k_len,
        v_len=v_len,
        native_ctx=_int(meta, f"{arch}.context_length") if arch else None,
        n_experts=(_int(meta, f"{arch}.expert_count") or 0) if arch else 0,
        n_experts_used=(_int(meta, f"{arch}.expert_used_count") or 0) if arch else 0,
        has_mtp=has_mtp or bool(arch and _int(meta, f"{arch}.nextn_predict_layers")),
        needs_mmproj=needs_mmproj,
        ssm_conv_kernel=_int(meta, f"{arch}.ssm.conv_kernel") if arch else None,
        ssm_state_size=_int(meta, f"{arch}.ssm.state_size") if arch else None,
        ssm_inner_size=_int(meta, f"{arch}.ssm.inner_size") if arch else None,
        ssm_group_count=_int(meta, f"{arch}.ssm.group_count") if arch else None,
        source=source,
    )


# Opening a multi-GB header costs 5-11 seconds, because the reader parses every
# tensor's metadata. Memoise per process, keyed on size+mtime so an edited or
# replaced file is re-read. This mirrors ``estimates._gguf_meta_mem``.
_facts_memo: dict[str, tuple[tuple[int, int], ArchFacts]] = {}

# On-disk cache mirroring estimates._meta_cache_file/_load_meta_cache/
# _store_meta_cache: same cache_dir(), a distinct filename so the two caches
# never collide, and its own version constant so a change to ArchFacts's shape
# invalidates old entries instead of crashing on them. Without this, shadow
# mode reopens the multi-GB header on the first estimate after every server
# restart (~5.5s measured on a real file) -- the in-process memo above only
# helps within one process's lifetime.
_FACTS_CACHE_FILENAME = "truth_facts_cache.json"
_FACTS_CACHE_VERSION = 1  # bump when ArchFacts's fields change

_ARCHFACTS_FIELDS = tuple(ArchFacts.__dataclass_fields__)


def _signature(path: Path | str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
        return (st.st_size, int(st.st_mtime))
    except OSError:
        return None


def _facts_cache_file() -> Path | None:
    try:
        from ..paths import cache_dir
        return cache_dir() / _FACTS_CACHE_FILENAME
    except Exception:
        return None


def _load_facts_cache() -> dict:
    path = _facts_cache_file()
    if not path or not path.is_file():
        return {}
    try:
        import json
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("_version", 1) != _FACTS_CACHE_VERSION:
            return {}
        return data
    except Exception:
        return {}


def _facts_from_cache_entry(entry: dict) -> ArchFacts:
    kwargs = {name: entry.get(name) for name in _ARCHFACTS_FIELDS}
    kwargs["attn_layer_indices"] = tuple(entry.get("attn_layer_indices") or ())
    return ArchFacts(**kwargs)


def _store_facts_cache(key: str, sig: tuple[int, int], facts: ArchFacts) -> None:
    path = _facts_cache_file()
    if not path:
        return
    try:
        import dataclasses
        import json
        data = _load_facts_cache()
        data["_version"] = _FACTS_CACHE_VERSION
        entry = dataclasses.asdict(facts)
        entry["attn_layer_indices"] = list(entry["attn_layer_indices"])
        entry["size"] = sig[0]
        entry["mtime"] = sig[1]
        data[key] = entry
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def read_facts(path: Path | str) -> ArchFacts:
    key = str(path)
    sig = _signature(key)
    cached = _facts_memo.get(key)
    if cached is not None and sig is not None and cached[0] == sig:
        return cached[1]

    if sig is not None:
        disk_entry = _load_facts_cache().get(key)
        if (disk_entry and disk_entry.get("size") == sig[0]
                and disk_entry.get("mtime") == sig[1]):
            try:
                facts = _facts_from_cache_entry(disk_entry)
                _facts_memo[key] = (sig, facts)
                return facts
            except Exception:
                pass  # corrupt/unreadable entry: fall through and recompute

    reader = gguf.GGUFReader(key)
    meta: dict = {}
    for field_key, field in reader.fields.items():
        # tokenizer.ggml.tokens/merges/token_type are ~250k-element arrays on a
        # modern vocab. Materialising them costs seconds and hundreds of MB, and
        # nothing here is memory-relevant. Skip them.
        if field_key.startswith("tokenizer."):
            continue
        contents = getattr(field, "contents", None)
        if callable(contents):
            try:
                meta[field_key] = contents()
            except Exception:
                continue

    facts = _facts_from_kv_and_tensors(meta, [t.name for t in reader.tensors])
    if sig is not None:
        _facts_memo[key] = (sig, facts)
        _store_facts_cache(key, sig, facts)
    return facts


_GGUF_MAGIC = b"GGUF"

# GGUF metadata value type tags -> struct format
_SCALAR_FMT = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i",
               6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}
_TYPE_STRING = 8
_TYPE_ARRAY = 9


class _Cursor:
    def __init__(self, buf: bytes):
        self._buf = io.BytesIO(buf)
        self._len = len(buf)

    def take(self, fmt: str):
        size = struct.calcsize(fmt)
        raw = self._buf.read(size)
        if len(raw) != size:
            raise ValueError("truncated GGUF header")
        return struct.unpack("<" + fmt, raw)[0]

    def string(self) -> str:
        length = self.take("Q")
        raw = self._buf.read(length)
        if len(raw) != length:
            raise ValueError("truncated GGUF header")
        return raw.decode("utf-8", "replace")

    def value(self, type_tag: int, keep: bool = True):
        """Read one value. With `keep` False the bytes are consumed but not
        materialised — used for the ~250k-element tokenizer arrays, which must
        be walked to stay byte-aligned but are never needed."""
        if type_tag == _TYPE_STRING:
            text = self.string()
            return text if keep else None
        if type_tag == _TYPE_ARRAY:
            elem_type = self.take("I")
            count = self.take("Q")
            if not keep:
                for _ in range(count):
                    self.value(elem_type, keep=False)
                return None
            return [self.value(elem_type) for _ in range(count)]
        fmt = _SCALAR_FMT.get(type_tag)
        if fmt is None:
            raise ValueError(f"unknown GGUF value type {type_tag}")
        result = self.take(fmt)
        return result if keep else None


def parse_header_bytes(buf: bytes) -> ArchFacts:
    """Build ArchFacts from raw GGUF header bytes.

    Accepts a prefix of the file: everything needed lives in the metadata and
    tensor-info sections, before any tensor data.
    """
    if buf[:4] != _GGUF_MAGIC:
        raise ValueError("not a GGUF file")
    cursor = _Cursor(buf)
    cursor.take("I")  # magic, already checked
    cursor.take("I")  # version
    n_tensors = cursor.take("Q")
    n_kv = cursor.take("Q")

    meta: dict = {}
    for _ in range(n_kv):
        key = cursor.string()
        type_tag = cursor.take("I")
        keep = not key.startswith("tokenizer.")
        value = cursor.value(type_tag, keep=keep)
        if keep:
            meta[key] = value

    names: list[str] = []
    for _ in range(n_tensors):
        name = cursor.string()
        n_dims = cursor.take("I")
        for _ in range(n_dims):
            cursor.take("Q")
        cursor.take("I")  # ggml type
        cursor.take("Q")  # offset
        names.append(name)

    return _facts_from_kv_and_tensors(meta, names)


def read_facts_remote(url: str, *, max_bytes: int = 32_000_000) -> ArchFacts:
    """Read facts from a remote GGUF without downloading the body.

    ``max_bytes`` must cover the metadata and tensor-info sections; 32 MB is
    ample for a 250k-token vocabulary plus ~1000 tensor entries.
    """
    request = urllib.request.Request(url, headers={"Range": f"bytes=0-{max_bytes - 1}"})
    with urllib.request.urlopen(request, timeout=120) as response:
        if response.status not in (200, 206):
            raise ValueError(f"range request failed: HTTP {response.status}")
        buf = response.read(max_bytes)
    return parse_header_bytes(buf)
