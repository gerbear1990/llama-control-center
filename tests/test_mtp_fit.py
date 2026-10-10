"""The fit badge and Smart Fit must price an embedded-MTP draft context.

Found 2026-10-10: profiles now register Qwen3.5+ models with
``spec_type=draft-mtp`` (no draft file), but neither estimator charged for the
draft context llama.cpp creates -- ~1.3 GB at 64k on Qwen3.8-27B, measured.
llama-fit-params can't see it either: it rejects --spec-type outright.
"""
from __future__ import annotations

from lcc_core import estimates
from lcc_core.fit import build_fit_args
from lcc_core.truth import gguf as truth_gguf
from lcc_core.truth.gguf import ArchFacts

from gguf_fixtures import write_minimal_gguf

MIB = 1024 ** 2

QWEN38 = ArchFacts(
    arch="qwen35", n_layers=65, attn_layer_indices=tuple(range(3, 64, 4)),
    total_kv_heads=64, k_len=256, v_len=256, native_ctx=262144,
    n_experts=0, n_experts_used=0, has_mtp=True, n_nextn_layers=1,
    needs_mmproj=True, ssm_conv_kernel=4, ssm_state_size=128,
    ssm_inner_size=6144, ssm_group_count=16, source="tensor-scan",
)
MODEL = {"path": "qwen38.gguf", "size_bytes": 20 * 1024 ** 3, "params_b": 27}
HW = {"primary_gpu": {"name": "RTX 5090", "vram_total_bytes": 32607 * MIB}}
BASE = {"ctx_size": 65536, "cache_type_k": "q8_0", "cache_type_v": "q8_0", "gpu_layers": 999}
MTP = {**BASE, "spec_type": "draft-mtp", "spec_draft_n_max": 4}


def _warm(monkeypatch, facts=QWEN38):
    monkeypatch.setattr(truth_gguf, "peek_facts", lambda path: facts)
    monkeypatch.setattr(truth_gguf, "read_facts", lambda path: facts)


def test_embedded_mtp_is_priced(monkeypatch):
    _warm(monkeypatch)
    base = estimates.estimate_memory_fit(BASE, MODEL, HW)["estimated"]
    mtp = estimates.estimate_memory_fit(MTP, MODEL, HW)["estimated"]
    # 256 MiB draft KV (f16) + 4 x 149.625 recurrent copies + 132 draft compute.
    assert mtp["spec_draft_mib"] == round(256 + 4 * 149.625 + 132)
    assert abs(mtp["accelerator_used_mib"] - base["accelerator_used_mib"] - 986.5) <= 0.5
    assert base["spec_draft_mib"] is None


def test_draft_kv_grows_with_context(monkeypatch):
    _warm(monkeypatch)
    at64 = estimates.estimate_memory_fit(MTP, MODEL, HW)["estimated"]["spec_draft_mib"]
    at128 = estimates.estimate_memory_fit({**MTP, "ctx_size": 131072}, MODEL, HW)["estimated"]["spec_draft_mib"]
    assert at128 - at64 == 256  # one f16 layer, 4 KiB/token


def test_cold_header_warns_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(truth_gguf, "peek_facts", lambda path: None)

    def _boom(path):
        raise AssertionError("badge path must not parse a header")

    monkeypatch.setattr(truth_gguf, "read_facts", _boom)
    fit = estimates.estimate_memory_fit(MTP, MODEL, HW)
    assert fit["estimated"]["spec_draft_mib"] is None
    assert any("MTP" in w and "not priced" in w for w in fit["warnings"])


def test_separate_draft_file_is_not_the_embedded_path(monkeypatch):
    _warm(monkeypatch)
    fit = estimates.estimate_memory_fit({**MTP, "draft_model": "mtp-x.gguf"}, MODEL, HW)
    assert fit["estimated"]["spec_draft_mib"] is None
    assert not any("MTP" in w for w in fit["warnings"])


def test_smart_fit_reserves_the_draft_context(monkeypatch):
    _warm(monkeypatch)
    base = build_fit_args("llama-fit-params", "qwen38.gguf", BASE, target_mib=1024)
    mtp = build_fit_args("llama-fit-params", "qwen38.gguf", MTP, target_mib=1024)
    assert base[base.index("-fitt") + 1] == "1024"
    assert mtp[mtp.index("-fitt") + 1] == str(1024 + 987)  # ceil(986.5)
    assert "--spec-type" not in mtp  # llama-fit-params rejects it


def test_legacy_reader_drops_the_nextn_block(tmp_path):
    path = write_minimal_gguf(
        tmp_path / "mtp.gguf",
        arch="qwen35moe", n_layer=41, attn_layers=[3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 40],
        n_kv_heads=2, k_len=256, v_len=256,
        extra_kv={"nextn_predict_layers": 1},
    )
    _n_layer, kv_dims, _tools, _ctx = estimates._parse_gguf_meta(str(path))
    assert kv_dims == (20, 256, 256)  # 10 layers x 2 heads, not 11
