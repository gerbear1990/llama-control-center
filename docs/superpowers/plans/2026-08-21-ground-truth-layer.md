# Ground-Truth Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make LCC's memory-fit figures trustworthy by deriving them from GGUF ground truth instead of tunable coefficients, starting with a measured 9% KV error on hybrid models.

**Architecture:** A new `lcc_core/truth/` package with two pure modules — `gguf.py` (facts from a file) and `kv.py` (arithmetic over those facts). Neither performs I/O beyond reading a header. Existing `estimates.py` becomes a consumer. Shadow mode runs the new path alongside the old one and logs disagreement without changing any displayed number.

**Tech Stack:** Python 3.10+, `gguf>=0.19.0` (already a dependency), pytest, stdlib `urllib` for range requests.

**Spec:** `docs/superpowers/specs/2026-08-21-ground-truth-layer-design.md`

## Global Constraints

- `requires-python = ">=3.10"`. `X | None` union syntax is fine; `match` statements and 3.11+ typing features are not.
- `gguf>=0.19.0` is already declared in `pyproject.toml` and `requirements.txt`. Do not add a second GGUF parser dependency.
- **Never `git add models.json`.** Stage explicit paths in every commit; never `git add -A` or `git add .`.
- **Never start the LCC API from an agent session** — startup autoscan rewrites `models.json`.
- The repository has pre-existing uncommitted changes in `lcc_api/app.py`, `lcc_api/static/app.js`, `lcc_api/static/index.html`, `lcc_api/static/styles.css` and `TODO.md`. These belong to the operator. Do not stage, revert, or commit them.
- Tests must not depend on multi-gigabyte model files. Use synthetic GGUF fixtures.
- **Run tests with `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest` from the repository root.** The project `.venv` does NOT have pytest installed; the system Python 3.13 does (pytest 9.1.1, gguf, numpy). Every `.venv/Scripts/python.exe` command in the task steps below should use this interpreter instead.
- **Known-failing baseline on this branch (NOT caused by this work — do not fix, do not chase):**
  `tests/test_launch_smoke.py::LaunchSmokeTests::test_launch_smoke_18717`,
  `tests/test_lcc_core.py::PortAvailabilityTests::test_next_free_port_skips_windows_reserved_range`,
  `tests/test_lcc_core.py::PortAvailabilityTests::test_windows_reserved_range_detected_via_probe`.
  A clean checkout of the base commit reports `3 failed, 176 passed, 4 skipped`. Your task is done when your new tests pass and no NEW failure appears.

**Scope:** This plan covers steps 0-3 of the spec's sequencing, stopping at shadow mode. Flipping the displayed numbers over to the truth layer is deliberately deferred to a follow-up plan, because that decision should be made with real divergence data in hand rather than in advance. Steps 4-6 (`build.py`, `observed.py`, `relevance.py`) get their own plan.

---

### Task 1: Fix attention-layer detection order

The Ornith defect, shipped on its own. `_extract_n_attn_layers` tries `full_attention_interval` first and returns `n_layer // interval`, which short-circuits before the tensor scan that would have given the right answer. On `Ornith-1.5-35B-A3B` this yields 10 instead of 11, underestimating KV by 9%.

**Files:**
- Create: `tests/gguf_fixtures.py`
- Modify: `lcc_core/estimates.py:184-227` (`_extract_n_attn_layers`), and the `_KV_META_CACHE_VERSION` constant near line 296
- Test: `tests/test_lcc_core.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `tests/gguf_fixtures.write_minimal_gguf(path, *, arch, n_layer, attn_layers, n_kv_heads, k_len, v_len, extra_kv=None) -> Path` — used by Tasks 2, 3 and 4.

- [ ] **Step 1: Write the fixture builder**

Tests need real GGUF files small enough to live in a temp dir. `gguf.GGUFWriter` produces them.

```python
# tests/gguf_fixtures.py
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
```

- [ ] **Step 2: Write the failing test**

The Ornith shape exactly: 41 layers, `full_attention_interval = 4`, but 11 layers carrying `attn_k` because the MTP layer at index 40 has one too.

```python
# tests/test_lcc_core.py — append
import gguf as _gguf_pkg

from tests.gguf_fixtures import write_minimal_gguf
from lcc_core import estimates as E


def test_attn_layer_count_prefers_tensor_scan_over_interval(tmp_path):
    """Ornith shape: 41 blocks, interval 4, but 11 layers really carry attn_k.

    41 // 4 == 10, which misses the MTP layer at index 40. The tensor scan is
    ground truth and must win.
    """
    attn = [3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 40]
    path = write_minimal_gguf(
        tmp_path / "hybrid.gguf",
        arch="qwen35moe",
        n_layer=41,
        attn_layers=attn,
        n_kv_heads=2,
        k_len=256,
        v_len=256,
        extra_kv={"full_attention_interval": 4},
    )
    reader = _gguf_pkg.GGUFReader(str(path))
    assert E._extract_n_attn_layers(reader, "qwen35moe", 41) == 11


def test_attn_layer_count_falls_back_to_interval_when_no_tensors_match(tmp_path):
    """A file whose tensor names follow no known pattern still gets an answer."""
    path = write_minimal_gguf(
        tmp_path / "opaque.gguf",
        arch="mystery",
        n_layer=41,
        attn_layers=[],
        n_kv_heads=2,
        k_len=256,
        v_len=256,
        extra_kv={"full_attention_interval": 4},
    )
    reader = _gguf_pkg.GGUFReader(str(path))
    assert E._extract_n_attn_layers(reader, "mystery", 41) == 10
```

- [ ] **Step 3: Run tests to verify the first fails**

Run: `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_lcc_core.py -k attn_layer_count -v`

Expected: `test_attn_layer_count_prefers_tensor_scan_over_interval` FAILS with `assert 10 == 11`. The fallback test PASSES already.

- [ ] **Step 4: Invert the detection order**

In `lcc_core/estimates.py`, replace the body of `_extract_n_attn_layers` so the tensor scan runs first and the interval metadata becomes the fallback. Update the docstring's numbered priority list to match — a docstring that contradicts the code is how this defect survived review.

```python
def _extract_n_attn_layers(reader, arch: str | None, n_layer: int | None) -> int | None:
    """Number of layers that contribute to the KV cache.

    Hybrid SSM+attention architectures (e.g. Qwen3.5, Jamba) interleave standard
    attention layers with pure SSM/Mamba layers that use a fixed-size recurrent
    state instead of a growing KV cache. Only the attention layers grow VRAM with
    context length, so the KV-cache multiplier must use the attention-layer count,
    not the total block count.

    Detection priority:
    1. Tensor scan: count layers with explicit ``attn_k.weight`` / ``attn_v.weight``
       tensors. SSM-only layers lack these. This is ground truth.
    2. Architecture-specific interval metadata (``full_attention_interval``), for
       files whose tensor names match no known pattern. Note this is a derived
       shortcut: ``n_layer // interval`` cannot see an MTP/nextn layer that also
       carries attention, which is why it is not tried first.
    3. Fall back to ``n_layer`` (standard all-attention architecture).
    """
    attn_layers: set[int] = set()
    for tensor in reader.tensors:
        name = tensor.name
        # An attention layer exposes per-head K/V projections; an SSM/Mamba
        # layer has a fixed recurrent state instead and lacks these. Match
        # the standard ``.attn_k.weight`` / ``.attn_v.weight`` suffix plus the
        # HF-style ``k_proj`` / ``v_proj`` names, so the layer count isn't
        # undercounted on architectures that don't use ``blk.`` tensor naming.
        is_attn = (
            name.endswith(".attn_k.weight")
            or name.endswith(".attn_v.weight")
            or ".k_proj." in name
            or ".v_proj." in name
            or "attn_k" in name
            or "attn_v" in name
        )
        if not is_attn:
            continue
        idx = _layer_index_from_tensor(name)
        if idx is not None:
            attn_layers.add(idx)
    if attn_layers:
        return len(attn_layers)

    if arch:
        val = _gguf_field_value(reader.get_field(f"{arch}.full_attention_interval"))
        if isinstance(val, int) and val > 1 and isinstance(n_layer, int) and n_layer > 0:
            result = n_layer // val
            if result > 0:
                return result

    return n_layer
```

- [ ] **Step 5: Invalidate the on-disk cache**

Any machine that already ran LCC has the wrong count persisted in `gguf_meta_cache.json`. Bump the version constant near line 296 of `lcc_core/estimates.py`:

```python
_KV_META_CACHE_VERSION = 4  # bump when kv_dims computation changes to invalidate stale entries
```

- [ ] **Step 6: Run the full suite**

Run: `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/ -v`

Expected: PASS, including both new tests. If any pre-existing test asserted the old count for a hybrid fixture, that assertion encoded the bug — update it and say so in the commit body.

- [ ] **Step 7: Verify against the real file**

Run:

```bash
C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -c "
import sys; sys.path.insert(0,'.')
from lcc_core import estimates as E
import gguf
p=r'C:\Users\filth\models\Ornith-1.5-35B-A3B-GGUF\Ornith-1.5-35B-A3B-Q5_K_L.gguf'
r=gguf.GGUFReader(p)
print('n_attn:', E._extract_n_attn_layers(r,'qwen35moe',41))
print('kv_dims:', E._extract_kv_dims(r,'qwen35moe',41))
"
```

Expected: `n_attn: 11` and `kv_dims: (22, 256, 256)`. Before the fix these were `10` and `(20, 256, 256)`.

- [ ] **Step 8: Commit**

```bash
git add lcc_core/estimates.py tests/test_lcc_core.py tests/gguf_fixtures.py
git commit -m "fix(estimates): prefer tensor scan over full_attention_interval for attention-layer count

The interval shortcut computes n_layer // interval, which misses an MTP/nextn
layer that also carries attn_k. On Ornith-1.5-35B-A3B this returned 10 instead
of 11, underestimating KV cache by 9% (20.0 vs 22.0 KiB/token, 5.0 vs 5.5 GiB
at 262k context). Underestimates are the dangerous direction: fit reports Good,
then the load OOMs.

Bumps _KV_META_CACHE_VERSION to invalidate persisted wrong values."
```

---

### Task 2: `truth/gguf.py` — typed facts from a local file

Consolidate the extraction logic that currently lives in seven private functions of a 1,002-line module into one typed, testable interface.

**Files:**
- Create: `lcc_core/truth/__init__.py`, `lcc_core/truth/gguf.py`
- Test: `tests/test_truth_gguf.py`

**Interfaces:**
- Consumes: `tests/gguf_fixtures.write_minimal_gguf` from Task 1.
- Produces:
  - `lcc_core.truth.gguf.ArchFacts` — frozen dataclass, fields listed in Step 1.
  - `lcc_core.truth.gguf.read_facts(path: Path | str) -> ArchFacts`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_truth_gguf.py
from pathlib import Path

from tests.gguf_fixtures import write_minimal_gguf
from lcc_core.truth.gguf import ArchFacts, read_facts


def test_read_facts_hybrid_counts_attention_layers_from_tensors(tmp_path):
    attn = [3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 40]
    path = write_minimal_gguf(
        tmp_path / "hybrid.gguf",
        arch="qwen35moe",
        n_layer=41,
        attn_layers=attn,
        n_kv_heads=2,
        k_len=256,
        v_len=256,
        extra_kv={"full_attention_interval": 4},
    )
    facts = read_facts(path)
    assert facts.arch == "qwen35moe"
    assert facts.n_layers == 41
    assert facts.attn_layer_indices == tuple(attn)
    assert facts.total_kv_heads == 22          # 11 layers x 2 KV heads
    assert facts.k_len == 256 and facts.v_len == 256
    assert facts.n_ssm_layers == 30            # 41 - 11
    assert facts.source == "tensor-scan"


def test_read_facts_dense_model(tmp_path):
    path = write_minimal_gguf(
        tmp_path / "dense.gguf",
        arch="llama",
        n_layer=32,
        attn_layers=list(range(32)),
        n_kv_heads=8,
        k_len=128,
        v_len=128,
    )
    facts = read_facts(path)
    assert facts.n_layers == 32
    assert facts.total_kv_heads == 256         # 32 x 8
    assert facts.n_ssm_layers == 0
    assert facts.source == "tensor-scan"


def test_read_facts_memoises_on_size_and_mtime(tmp_path):
    """Parsing a real header costs 5-11s, so a repeat read must be served from
    the memo rather than reopening the file."""
    path = write_minimal_gguf(
        tmp_path / "memo.gguf",
        arch="llama",
        n_layer=4,
        attn_layers=[0, 1, 2, 3],
        n_kv_heads=2,
        k_len=64,
        v_len=64,
    )
    assert read_facts(path) is read_facts(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_truth_gguf.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'lcc_core.truth'`

- [ ] **Step 3: Create the package**

```python
# lcc_core/truth/__init__.py
"""Ground truth about models, builds and real runs.

Each module answers one question from one source and holds no opinions:

- ``gguf``     — what is this model?      (the file)
- ``kv``       — what will it cost?       (arithmetic over gguf facts)

See docs/superpowers/specs/2026-08-21-ground-truth-layer-design.md.
"""
```

- [ ] **Step 4: Write the implementation**

```python
# lcc_core/truth/gguf.py
"""Typed architecture facts read from a GGUF header.

This wraps the ``gguf`` package rather than parsing bytes: ``GGUFReader`` is
already a project dependency and already used by ``estimates``. What this module
adds is a typed surface, a single tested code path, and explicit provenance for
how the attention-layer count was determined.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import gguf

_LAYER_RE = re.compile(r"(?:blk|layers?)\.(\d+)\.")

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
    match = _LAYER_RE.search(name)
    return int(match.group(1)) if match else None


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
        source=source,
    )


# Opening a multi-GB header costs 5-11 seconds, because the reader parses every
# tensor's metadata. Memoise per process, keyed on size+mtime so an edited or
# replaced file is re-read. This mirrors ``estimates._gguf_meta_mem``.
_facts_memo: dict[str, tuple[tuple[int, int], ArchFacts]] = {}


def _signature(path: Path | str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
        return (st.st_size, int(st.st_mtime))
    except OSError:
        return None


def read_facts(path: Path | str) -> ArchFacts:
    key = str(path)
    sig = _signature(key)
    cached = _facts_memo.get(key)
    if cached is not None and sig is not None and cached[0] == sig:
        return cached[1]

    reader = gguf.GGUFReader(key)
    meta: dict = {}
    for field_key, field in reader.fields.items():
        contents = getattr(field, "contents", None)
        if callable(contents):
            try:
                meta[field_key] = contents()
            except Exception:
                continue

    facts = _facts_from_kv_and_tensors(meta, [t.name for t in reader.tensors])
    if sig is not None:
        _facts_memo[key] = (sig, facts)
    return facts
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_truth_gguf.py -v`

Expected: PASS (3 tests)

- [ ] **Step 6: Add the golden fixture test against real models**

These files exist on the operator's machine but not in CI, so the test skips when absent. Reading a header costs 5-11 seconds per multi-GB file, which is why this is a separate test rather than folded into the unit tests.

```python
# tests/test_truth_gguf.py — append
import pytest

ORNITH = Path(r"C:\Users\filth\models\Ornith-1.5-35B-A3B-GGUF\Ornith-1.5-35B-A3B-Q5_K_L.gguf")


@pytest.mark.skipif(not ORNITH.exists(), reason="model not present on this machine")
def test_golden_ornith():
    """Hand-verified against the GGUF header on 2026-08-21."""
    facts = read_facts(ORNITH)
    assert facts.arch == "qwen35moe"
    assert facts.n_layers == 41
    assert facts.attn_layer_indices == (3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 40)
    assert facts.total_kv_heads == 22
    assert facts.k_len == 256 and facts.v_len == 256
    assert facts.native_ctx == 262144
    assert facts.n_experts == 256 and facts.n_experts_used == 8
    assert facts.has_mtp is True
    assert facts.needs_mmproj is True
    assert facts.is_hybrid and facts.n_ssm_layers == 30
    assert facts.ssm_conv_kernel == 4 and facts.ssm_state_size == 128
    assert facts.ssm_inner_size == 4096
```

- [ ] **Step 7: Run the golden test**

Run: `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_truth_gguf.py -v`

Expected: PASS (4 tests). If `test_golden_ornith` fails on a field, the header is the authority — fix the code, not the assertion, and re-verify by dumping that field directly.

- [ ] **Step 8: Commit**

```bash
git add lcc_core/truth/__init__.py lcc_core/truth/gguf.py tests/test_truth_gguf.py
git commit -m "feat(truth): add typed ArchFacts extraction from GGUF headers

Consolidates layer/KV/context extraction that was spread across seven private
functions in estimates.py into one tested interface, and records how the
attention-layer count was determined (tensor-scan / interval-metadata /
assumed-dense) so downstream figures can carry provenance.

Adds facts estimates.py never read: expert counts, MTP presence, mmproj
requirement, and SSM state dimensions."
```

---

### Task 3: `truth/kv.py` — the arithmetic

Pure functions, zero I/O. This is the module the trust claim rests on, so it is written to be exhaustively testable.

**Files:**
- Create: `lcc_core/truth/kv.py`
- Test: `tests/test_truth_kv.py`

**Interfaces:**
- Consumes: `lcc_core.truth.gguf.ArchFacts` from Task 2.
- Produces:
  - `lcc_core.truth.kv.cache_bytes_per_elem(name: str | None) -> float`
  - `lcc_core.truth.kv.kv_bytes_per_token(facts, ctk="f16", ctv="f16") -> int | None`
  - `lcc_core.truth.kv.ssm_state_bytes(facts) -> int`
  - `lcc_core.truth.kv.Breakdown` — frozen dataclass
  - `lcc_core.truth.kv.breakdown(facts, *, weights_bytes, ctx, ctk="f16", ctv="f16", mmproj_bytes=0) -> Breakdown`

- [ ] **Step 1: Write the failing test**

Numbers below are hand-derived from the Ornith header and cross-checked against the spec's worked example.

```python
# tests/test_truth_kv.py
import pytest

from lcc_core.truth.gguf import ArchFacts
from lcc_core.truth import kv

GIB = 1024 ** 3


def _facts(**over) -> ArchFacts:
    base = dict(
        arch="qwen35moe", n_layers=41,
        attn_layer_indices=(3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 40),
        total_kv_heads=22, k_len=256, v_len=256, native_ctx=262144,
        n_experts=256, n_experts_used=8, has_mtp=True, needs_mmproj=True,
        ssm_conv_kernel=4, ssm_state_size=128, ssm_inner_size=4096,
        source="tensor-scan",
    )
    base.update(over)
    return ArchFacts(**base)


def test_kv_bytes_per_token_hybrid_f16():
    """22 KV heads x (256 + 256) x 2 bytes = 22528 B = 22.0 KiB."""
    assert kv.kv_bytes_per_token(_facts(), "f16", "f16") == 22528


def test_kv_bytes_per_token_q8_0_is_roughly_half():
    """q8_0 stores 8.5 bits per element: 22 x 512 x 1.0625 = 11968 B."""
    assert kv.kv_bytes_per_token(_facts(), "q8_0", "q8_0") == 11968


def test_kv_at_native_context_fits_the_spec_table():
    per_token = kv.kv_bytes_per_token(_facts(), "f16", "f16")
    assert round(per_token * 262144 / GIB, 1) == 5.5
    per_token_q8 = kv.kv_bytes_per_token(_facts(), "q8_0", "q8_0")
    assert round(per_token_q8 * 262144 / GIB, 1) == 2.9


def test_undercounting_the_mtp_layer_is_the_9_percent_bug():
    """The pre-fix code saw 10 attention layers (20 KV heads), not 11."""
    wrong = kv.kv_bytes_per_token(_facts(total_kv_heads=20), "f16", "f16")
    right = kv.kv_bytes_per_token(_facts(), "f16", "f16")
    assert wrong == 20480
    assert round((right - wrong) / right * 100) == 9


def test_ssm_state_is_constant_in_context():
    """30 SSM layers x (conv 4096x3 + state 4096x128) x 4 bytes f32."""
    facts = _facts()
    assert kv.ssm_state_bytes(facts) == 30 * (4096 * 3 + 4096 * 128) * 4
    assert round(kv.ssm_state_bytes(facts) / 1024 ** 2) == 61


def test_dense_model_has_no_ssm_state():
    facts = _facts(n_layers=32, attn_layer_indices=tuple(range(32)),
                   ssm_conv_kernel=None, ssm_state_size=None, ssm_inner_size=None)
    assert kv.ssm_state_bytes(facts) == 0


def test_breakdown_totals():
    facts = _facts()
    result = kv.breakdown(
        facts,
        weights_bytes=int(25.81e9),
        ctx=262144,
        ctk="q8_0", ctv="q8_0",
        mmproj_bytes=int(0.90e9),
    )
    assert result.kv_bytes == 11968 * 262144
    assert result.total_bytes == (
        result.weights_bytes + result.mmproj_bytes + result.kv_bytes + result.ssm_bytes
    )
    assert round(result.total_bytes / GIB, 1) == 27.8
    assert result.provenance == "computed"


def test_breakdown_is_unknown_when_kv_dims_missing():
    facts = _facts(total_kv_heads=None)
    result = kv.breakdown(facts, weights_bytes=1, ctx=4096)
    assert result.kv_bytes is None
    assert result.provenance == "unknown"


@pytest.mark.parametrize("name,expected", [
    ("f16", 2.0), ("F16", 2.0), ("bf16", 2.0), ("f32", 4.0),
    ("q8_0", 1.0625), ("q5_1", 0.75), ("q4_0", 0.5),
    (None, 2.0), ("nonsense", 2.0),
])
def test_cache_bytes_per_elem(name, expected):
    assert kv.cache_bytes_per_elem(name) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_truth_kv.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'lcc_core.truth.kv'`

- [ ] **Step 3: Write the implementation**

```python
# lcc_core/truth/kv.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_truth_kv.py -v`

Expected: PASS (14 tests, counting the parametrized cases)

- [ ] **Step 5: Commit**

```bash
git add lcc_core/truth/kv.py tests/test_truth_kv.py
git commit -m "feat(truth): add pure KV and SSM memory arithmetic

kv_bytes_per_token, ssm_state_bytes and breakdown are pure functions over
ArchFacts, so they are exhaustively testable and can later be checked against
what llama.cpp actually allocates.

Accounts for SSM recurrent state, which estimates.py never modelled, and
returns provenance 'unknown' rather than a fallback number when KV dimensions
cannot be read."
```

---

### Task 4: Remote header reads

Answer fit before committing to a multi-tens-of-GB download. `GGUFReader` memory-maps a local file and cannot do this, so this path is hand-rolled — but the parser is separated from the fetch so it is testable without a network.

**Files:**
- Modify: `lcc_core/truth/gguf.py`
- Test: `tests/test_truth_gguf.py`

**Interfaces:**
- Consumes: `ArchFacts`, `read_facts` from Task 2.
- Produces:
  - `lcc_core.truth.gguf.parse_header_bytes(buf: bytes) -> ArchFacts`
  - `lcc_core.truth.gguf.read_facts_remote(url: str, *, max_bytes: int = 32_000_000) -> ArchFacts`

- [ ] **Step 1: Write the failing test**

The parser is tested by feeding it the bytes of a synthetic file — same input a range request would return, no network involved.

```python
# tests/test_truth_gguf.py — append
from lcc_core.truth.gguf import parse_header_bytes


def test_parse_header_bytes_matches_reader(tmp_path):
    """The hand-rolled parser and GGUFReader must agree on the same file."""
    attn = [3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 40]
    path = write_minimal_gguf(
        tmp_path / "hybrid.gguf",
        arch="qwen35moe", n_layer=41, attn_layers=attn,
        n_kv_heads=2, k_len=256, v_len=256,
        extra_kv={"full_attention_interval": 4},
    )
    from_reader = read_facts(path)
    from_bytes = parse_header_bytes(path.read_bytes())
    assert from_bytes == from_reader


def test_parse_header_bytes_rejects_bad_magic():
    with pytest.raises(ValueError, match="not a GGUF"):
        parse_header_bytes(b"NOPE" + b"\x00" * 64)


def test_parse_header_bytes_rejects_truncation(tmp_path):
    path = write_minimal_gguf(
        tmp_path / "t.gguf", arch="llama", n_layer=4,
        attn_layers=[0, 1, 2, 3], n_kv_heads=2, k_len=64, v_len=64,
    )
    with pytest.raises(ValueError, match="truncated"):
        parse_header_bytes(path.read_bytes()[:32])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_truth_gguf.py -k parse_header -v`

Expected: FAIL with `ImportError: cannot import name 'parse_header_bytes'`

- [ ] **Step 3: Write the parser**

Append to `lcc_core/truth/gguf.py`. Refactor `read_facts` so both entry points build `ArchFacts` from the same `_facts_from_kv_and_tensors(meta, tensor_names)` helper — otherwise the two paths drift, which is the exact failure mode this whole design exists to prevent.

```python
import io
import struct
import urllib.request

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

    def value(self, type_tag: int):
        if type_tag == _TYPE_STRING:
            return self.string()
        if type_tag == _TYPE_ARRAY:
            elem_type = self.take("I")
            count = self.take("Q")
            return [self.value(elem_type) for _ in range(count)]
        fmt = _SCALAR_FMT.get(type_tag)
        if fmt is None:
            raise ValueError(f"unknown GGUF value type {type_tag}")
        return self.take(fmt)


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
        meta[key] = cursor.value(cursor.take("I"))

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
        buf = response.read()
    return parse_header_bytes(buf)
```

- [ ] **Step 4: Run the whole truth suite**

Run: `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_truth_gguf.py tests/test_truth_kv.py -v`

Expected: PASS, including `test_parse_header_bytes_matches_reader`, which is the assertion that both paths agree.

- [ ] **Step 5: Commit**

```bash
git add lcc_core/truth/gguf.py tests/test_truth_gguf.py
git commit -m "feat(truth): read GGUF facts remotely via HTTP range request

Lets fit be answered before committing to a multi-GB download. GGUFReader
memory-maps a local file and cannot do this, so the header parser is
hand-rolled, but both paths build ArchFacts through one shared function and a
test asserts they agree on the same file."
```

---

### Task 5: Shadow mode

Run the new path alongside the old one, log where they disagree, change nothing the operator sees. This produces the evidence for deciding whether to flip.

**Files:**
- Create: `lcc_core/truth/shadow.py`
- Modify: `lcc_core/estimates.py` (inside `estimate_memory_fit`, after `kv_cache_mib` is computed around line 740)
- Test: `tests/test_truth_shadow.py`

**Interfaces:**
- Consumes: `read_facts`, `breakdown` from Tasks 2-3.
- Produces: `lcc_core.truth.shadow.record_divergence(model_path, params, legacy_kv_mib) -> dict | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_truth_shadow.py
import json

from tests.gguf_fixtures import write_minimal_gguf
from lcc_core.truth import shadow


def test_records_divergence_between_legacy_and_truth(tmp_path, monkeypatch):
    path = write_minimal_gguf(
        tmp_path / "m.gguf", arch="llama", n_layer=4,
        attn_layers=[0, 1, 2, 3], n_kv_heads=2, k_len=64, v_len=64,
    )
    log = tmp_path / "divergence.jsonl"
    monkeypatch.setattr(shadow, "_log_path", lambda: log)

    # truth: 8 KV heads x 128 x 2 B = 2048 B/token x 4096 ctx = 8 MiB
    result = shadow.record_divergence(
        str(path), {"ctx_size": 4096, "cache_type_k": "f16", "cache_type_v": "f16"},
        legacy_kv_mib=10.0,
    )
    assert result is not None
    assert round(result["truth_kv_mib"], 1) == 8.0
    assert result["legacy_kv_mib"] == 10.0
    assert round(result["delta_pct"]) == 25   # legacy is 25% above truth

    entry = json.loads(log.read_text().strip())
    assert entry["arch"] == "llama"
    assert entry["source"] == "tensor-scan"


def test_never_raises_on_a_broken_file(tmp_path, monkeypatch):
    """Shadow mode must never break the fit path it observes."""
    broken = tmp_path / "broken.gguf"
    broken.write_bytes(b"NOPE" + b"\x00" * 64)
    monkeypatch.setattr(shadow, "_log_path", lambda: tmp_path / "d.jsonl")
    assert shadow.record_divergence(str(broken), {"ctx_size": 4096}, 10.0) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_truth_shadow.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'lcc_core.truth.shadow'`

- [ ] **Step 3: Write the implementation**

```python
# lcc_core/truth/shadow.py
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

from ..paths import cache_dir
from .gguf import read_facts
from .kv import breakdown

_LOG_FILENAME = "kv_divergence.jsonl"


def _log_path() -> Path:
    return cache_dir() / _LOG_FILENAME


def record_divergence(model_path: str | None, params: dict[str, Any],
                      legacy_kv_mib: float | None) -> dict[str, Any] | None:
    """Compare the legacy KV figure against the truth layer and append a record.

    Returns the comparison, or None if it could not be made. Never raises.
    """
    if not model_path or legacy_kv_mib is None:
        return None
    try:
        facts = read_facts(model_path)
        ctx = int(params.get("ctx_size") or 4096)
        result = breakdown(
            facts,
            weights_bytes=0,
            ctx=ctx,
            ctk=params.get("cache_type_k"),
            ctv=params.get("cache_type_v"),
        )
        if result.kv_bytes is None:
            return None
        truth_mib = result.kv_bytes / 1024 / 1024
        delta_pct = ((legacy_kv_mib - truth_mib) / truth_mib * 100) if truth_mib else 0.0
        entry = {
            "model": Path(model_path).name,
            "arch": facts.arch,
            "source": facts.source,
            "n_layers": facts.n_layers,
            "n_attn_layers": facts.n_attn_layers,
            "ctx": ctx,
            "legacy_kv_mib": round(legacy_kv_mib, 2),
            "truth_kv_mib": round(truth_mib, 2),
            "delta_pct": round(delta_pct, 2),
        }
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        return entry
    except Exception:
        return None
```

`cache_dir()` is the same accessor `estimates._meta_cache_file` uses, so the divergence log lands beside `gguf_meta_cache.json`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/test_truth_shadow.py -v`

Expected: PASS (2 tests)

- [ ] **Step 5: Wire it into the fit path**

In `lcc_core/estimates.py`, immediately after `kv_cache_mib` is assigned (around line 740-743), add the observation call. It must be after the value exists and before it is used, and it must not alter any variable:

```python
    # Shadow mode: observe how the truth layer would have answered. Logs only;
    # the displayed figure is unchanged. See docs/superpowers/specs/
    # 2026-08-21-ground-truth-layer-design.md
    if probe_model:
        try:
            from .truth import shadow as _shadow
            _m = model or {}
            _shadow.record_divergence(
                _m.get("path") or _m.get("model_path"), params, kv_cache_mib
            )
        except Exception:
            pass
```

Gate on `probe_model` so batch callers such as the profiles-list refresh stay fast — the same reason `_kv_dims` is gated. The `path` / `model_path` fallback mirrors `estimates._kv_dims`.

- [ ] **Step 6: Run the full suite**

Run: `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest tests/ -v`

Expected: PASS. No existing assertion should change — shadow mode alters no output.

- [ ] **Step 7: Verify no behaviour change**

Confirm `estimate_memory_fit` returns identical output with shadow mode present:

```bash
C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -c "
import sys; sys.path.insert(0,'.')
from lcc_core.estimates import estimate_memory_fit
params={'ctx_size':262144,'cache_type_k':'q8_0','cache_type_v':'q8_0'}
model={'path':r'C:\Users\filth\models\Ornith-1.5-35B-A3B-GGUF\Ornith-1.5-35B-A3B-Q5_K_L.gguf','size_mib':24615}
out=estimate_memory_fit(params, model, {}, probe_model=True)
print({k:out[k] for k in sorted(out) if 'kv' in k or 'status' in k})
"
```

Expected: a fit dict as before, plus a new line appended to `kv_divergence.jsonl`.

- [ ] **Step 8: Commit**

```bash
git add lcc_core/truth/shadow.py lcc_core/estimates.py tests/test_truth_shadow.py
git commit -m "feat(truth): shadow-mode divergence logging

Computes the truth-layer KV figure alongside the legacy estimator and appends
the comparison to kv_divergence.jsonl. Displays nothing and changes no returned
value; it exists to gather evidence about whether the truth layer is ready to
replace the estimator, and on which architectures they disagree.

Gated on probe_model so batch refreshes stay fast, and swallows every exception
so it cannot break the path it observes."
```

---

## After this plan

Let shadow mode run over normal use, then read `kv_divergence.jsonl`:

```bash
C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -c "
import json,collections
rows=[json.loads(l) for l in open(__import__('lcc_core.paths',fromlist=['x']).cache_dir()/'kv_divergence.jsonl')]
by=collections.defaultdict(list)
for r in rows: by[(r['arch'],r['model'])].append(r['delta_pct'])
for k,v in sorted(by.items()): print(f'{k[0]:<14} {k[1][:44]:<44} n={len(v):>3} median={sorted(v)[len(v)//2]:>7.2f}%')
"
```

Models where the two agree within noise need no further work. Models where they diverge are the argument for flipping, and the divergence sign says which figure was wrong. That evidence feeds the follow-up plan covering spec steps 3-6: provenance labels and the flip, `truth/build.py`, `truth/observed.py`, and `relevance.py`.
