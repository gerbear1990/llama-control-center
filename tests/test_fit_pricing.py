"""Regression tests for VRAM/fit pricing: mmproj (#20), compute buffer (#21), and separate draft models (#22)."""
from __future__ import annotations

import math

from lcc_core import estimates
from lcc_core.fit import build_fit_args
from lcc_core.truth import gguf as truth_gguf
from lcc_core.truth.gguf import ArchFacts

from gguf_fixtures import write_minimal_gguf

MIB = 1024 ** 2

BASE_MODEL = {"path": "main.gguf", "size_bytes": 20 * 1024 ** 3, "params_b": 27}
HW = {"primary_gpu": {"name": "RTX 5090", "vram_total_bytes": 32607 * MIB}}
BASE_PARAMS = {"ctx_size": 65536, "cache_type_k": "q8_0", "cache_type_v": "q8_0", "gpu_layers": 999}

DRAFT_FACTS = ArchFacts(
    arch="qwen3", n_layers=2, attn_layer_indices=(0, 1),
    total_kv_heads=4, k_len=128, v_len=128, native_ctx=65536,
    n_experts=0, n_experts_used=0, has_mtp=False, n_nextn_layers=0,
    needs_mmproj=False, ssm_conv_kernel=None, ssm_state_size=None,
    ssm_inner_size=None, ssm_group_count=None, source="tensor-scan",
)


def _warm_main(monkeypatch):
    main_facts = ArchFacts(
        arch="qwen35", n_layers=64, attn_layer_indices=tuple(range(3, 64, 4)),
        total_kv_heads=64, k_len=256, v_len=256, native_ctx=262144,
        n_experts=0, n_experts_used=0, has_mtp=False, n_nextn_layers=0,
        needs_mmproj=True, ssm_conv_kernel=None, ssm_state_size=None,
        ssm_inner_size=None, ssm_group_count=None, source="tensor-scan",
    )
    monkeypatch.setattr(truth_gguf, "peek_facts", lambda path: main_facts)
    monkeypatch.setattr(truth_gguf, "read_facts", lambda path: main_facts)


def test_mmproj_file_is_charged_to_vram(monkeypatch, tmp_path):
    _warm_main(monkeypatch)
    mmproj_file = tmp_path / "mmproj-F16.gguf"
    mmproj_file.write_bytes(b"\x00" * (100 * MIB))

    base = estimates.estimate_memory_fit(BASE_PARAMS, BASE_MODEL, HW)["estimated"]
    with_mmproj = estimates.estimate_memory_fit(
        BASE_PARAMS, {**BASE_MODEL, "mmproj_path": str(mmproj_file)}, HW
    )["estimated"]

    assert base["mmproj_mib"] is None
    assert with_mmproj["mmproj_mib"] == 100
    assert with_mmproj["accelerator_used_mib"] - base["accelerator_used_mib"] == 100

    # params["mmproj"] and model["mmproj_bytes"] also resolve
    via_param = estimates.estimate_memory_fit(
        {**BASE_PARAMS, "mmproj": str(mmproj_file)}, BASE_MODEL, HW
    )["estimated"]
    assert via_param["mmproj_mib"] == 100

    via_bytes = estimates.estimate_memory_fit(
        BASE_PARAMS, {**BASE_MODEL, "mmproj_bytes": 50 * MIB}, HW
    )["estimated"]
    assert via_bytes["mmproj_mib"] == 50


def test_mmproj_cpu_only_charges_ram(monkeypatch, tmp_path):
    _warm_main(monkeypatch)
    mmproj_file = tmp_path / "mmproj-F16.gguf"
    mmproj_file.write_bytes(b"\x00" * (50 * MIB))
    cpu_params = {**BASE_PARAMS, "gpu_layers": 0}

    base = estimates.estimate_memory_fit(cpu_params, BASE_MODEL, HW)["estimated"]
    with_mmproj = estimates.estimate_memory_fit(
        cpu_params, {**BASE_MODEL, "mmproj_path": str(mmproj_file)}, HW
    )["estimated"]

    assert with_mmproj["accelerator_used_mib"] == base["accelerator_used_mib"] == 0
    assert with_mmproj["ram_used_mib"] - base["ram_used_mib"] == 50


def test_mmproj_missing_or_directory_is_ignored(monkeypatch, tmp_path):
    _warm_main(monkeypatch)
    missing = tmp_path / "does-not-exist-mmproj.gguf"
    assert estimates.estimate_memory_fit(
        BASE_PARAMS, {**BASE_MODEL, "mmproj_path": str(missing)}, HW
    )["estimated"]["mmproj_mib"] is None
    assert estimates.estimate_memory_fit(
        BASE_PARAMS, {**BASE_MODEL, "mmproj_path": str(tmp_path)}, HW
    )["estimated"]["mmproj_mib"] is None


def test_compute_buffer_calibrated_near_measured(monkeypatch):
    _warm_main(monkeypatch)
    fit = estimates.estimate_memory_fit(BASE_PARAMS, BASE_MODEL, HW)["estimated"]
    # llama.cpp b11349 measured 400.28 MiB at -c 65536, default batch, FA on
    assert 380 <= fit["compute_mib"] <= 420

    no_fa = estimates.estimate_memory_fit(
        {**BASE_PARAMS, "flash_attn": False}, BASE_MODEL, HW
    )["estimated"]
    assert no_fa["compute_mib"] > fit["compute_mib"]


def test_separate_draft_model_is_priced_in_badge_and_smart_fit(monkeypatch, tmp_path):
    draft_file = tmp_path / "mtp-draft.gguf"
    write_minimal_gguf(
        draft_file,
        arch="qwen3", n_layer=2, attn_layers=[0, 1],
        n_kv_heads=2, k_len=128, v_len=128,
    )
    # Pad the synthetic GGUF to 10 MiB so file size is a clean number.
    with draft_file.open("ab") as fh:
        current = draft_file.stat().st_size
        fh.write(b"\x00" * (10 * MIB - current))

    # Exercise real GGUF header parsing on probe_model=True (no monkeypatch on truth_gguf).
    base = estimates.estimate_memory_fit(BASE_PARAMS, BASE_MODEL, HW)["estimated"]
    draft_params = {**BASE_PARAMS, "draft_model": str(draft_file)}
    with_draft = estimates.estimate_memory_fit(
        draft_params, BASE_MODEL, HW, probe_model=True
    )["estimated"]

    # Expected: 10 MiB file + 132 MiB compute + draft KV at f16 default:
    # 2 layers * 2 kv_heads = 4 total_kv_heads; 65536 * (4*128*2 + 4*128*2) = 128 MiB -> 270 MiB.
    assert with_draft["spec_draft_mib"] == 270
    assert with_draft["accelerator_used_mib"] - base["accelerator_used_mib"] == 270

    # Quantized draft KV (-ctkd/-ctvd q8_0 -> 1.0625 B/elem -> 68 MiB) reduces total.
    q8_draft_params = {**draft_params, "cache_type_k_draft": "q8_0", "cache_type_v_draft": "q8_0"}
    with_q8_draft = estimates.estimate_memory_fit(
        q8_draft_params, BASE_MODEL, HW, probe_model=True
    )["estimated"]
    assert with_q8_draft["spec_draft_mib"] == 10 + 132 + 68

    # Setting spec_type="draft-mtp" alongside draft_model must not double-count.
    both_params = {**draft_params, "spec_type": "draft-mtp"}
    with_both = estimates.estimate_memory_fit(
        both_params, BASE_MODEL, HW, probe_model=True
    )["estimated"]
    assert with_both["spec_draft_mib"] == 270

    # Smart Fit reserves the draft model in -fitt (and does not on CPU-only).
    fit_args = build_fit_args("llama-fit-params", "main.gguf", draft_params, target_mib=1024)
    assert fit_args[fit_args.index("-fitt") + 1] == str(1024 + int(math.ceil(270)))
    cpu_fit_args = build_fit_args(
        "llama-fit-params", "main.gguf", {**draft_params, "gpu_layers": 0}, target_mib=1024
    )
    assert cpu_fit_args[cpu_fit_args.index("-fitt") + 1] == "1024"


def test_separate_draft_cold_cache_and_missing_warnings(monkeypatch, tmp_path):
    draft_file = tmp_path / "draft.gguf"
    draft_file.write_bytes(b"\x00" * (10 * MIB))

    monkeypatch.setattr(truth_gguf, "peek_facts", lambda path: None)
    cold = estimates.estimate_memory_fit(
        {**BASE_PARAMS, "draft_model": str(draft_file)}, BASE_MODEL, HW, probe_model=False
    )
    assert cold["estimated"]["spec_draft_mib"] == 10 + 132
    assert any("KV cache is not priced yet" in w for w in cold["warnings"])

    missing = estimates.estimate_memory_fit(
        {**BASE_PARAMS, "draft_model": str(tmp_path / "missing-draft.gguf")}, BASE_MODEL, HW
    )
    assert missing["estimated"]["spec_draft_mib"] is None
    assert any("file could not be read" in w for w in missing["warnings"])
