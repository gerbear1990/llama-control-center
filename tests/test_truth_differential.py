"""Differential coverage across every real GGUF on disk (Finding 6).

The spec asked for golden fixtures across every GGUF on disk; hardcoding one
model at a time is a losing race against what's actually on the operator's
drive. This instead asserts the truth layer and the legacy estimator agree on
KV dimensions for *every* GGUF found under ``C:\\Users\\filth\\models``, which
is strictly stronger than a handful of golden fixtures and directly guards
the live drift risk between the two implementations (see Finding 1, which was
exactly this kind of silent drift).

Marked ``slow`` so it's easy to deselect (``-m "not slow"``) if the model
directory grows large; the on-disk caches from Finding 3 (truth) and the
pre-existing legacy meta cache make repeat runs fast regardless.
"""
from __future__ import annotations

from pathlib import Path

import gguf
import pytest

from lcc_core import estimates
from lcc_core.truth.gguf import read_facts

MODELS_DIR = Path(r"C:\Users\filth\models")


def _find_gguf_files() -> list[Path]:
    if not MODELS_DIR.is_dir():
        return []
    return sorted(MODELS_DIR.rglob("*.gguf"))


def _legacy_kv_dims(path: Path) -> tuple[int, int, int] | None:
    """Open our own reader so we can call ``_extract_kv_dims`` directly,
    exactly mirroring how ``estimates._parse_gguf_meta`` derives arch/n_layer
    before it."""
    reader = gguf.GGUFReader(str(path))
    arch = estimates._gguf_field_value(reader.get_field("general.architecture"))
    if not isinstance(arch, str) or not arch:
        arch = None
    n_layer = estimates._extract_n_layer(reader, arch)
    return estimates._extract_kv_dims(reader, arch, n_layer)


@pytest.mark.slow
@pytest.mark.skipif(not MODELS_DIR.is_dir(), reason="models directory not present on this machine")
@pytest.mark.parametrize("path", _find_gguf_files(), ids=lambda p: p.name)
def test_truth_and_legacy_agree_on_kv_dims(path: Path):
    legacy_dims = _legacy_kv_dims(path)
    if legacy_dims is None:
        pytest.skip(f"{path.name}: no attention KV dims (non-text model, e.g. CLIP/video)")

    facts = read_facts(path)
    truth_dims = (facts.total_kv_heads, facts.k_len, facts.v_len)
    assert truth_dims == legacy_dims
