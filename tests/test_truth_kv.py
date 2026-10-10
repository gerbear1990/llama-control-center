import pytest

from lcc_core.truth.gguf import ArchFacts
from lcc_core.truth import kv

GIB = 1024 ** 3


def _facts(**over) -> ArchFacts:
    base = dict(
        arch="qwen35moe", n_layers=41,
        attn_layer_indices=(3, 7, 11, 15, 19, 23, 27, 31, 35, 39),
        total_kv_heads=20, k_len=256, v_len=256, native_ctx=262144,
        n_experts=256, n_experts_used=8, has_mtp=True, n_nextn_layers=1, needs_mmproj=True,
        ssm_conv_kernel=4, ssm_state_size=128, ssm_inner_size=4096,
        ssm_group_count=16,
        source="tensor-scan",
    )
    base.update(over)
    return ArchFacts(**base)


def test_kv_bytes_per_token_hybrid_f16():
    """20 KV heads x (256 + 256) x 2 bytes = 20480 B = 20.0 KiB.

    Ground truth, llama.cpp b11349 on Ornith-1.5-35B-A3B (qwen35moe, 41 blocks,
    nextn_predict_layers=1), -c 8192 f16: "160.00 MiB (8192 cells, 10 layers)"
    = 20480 B/token."""
    assert kv.kv_bytes_per_token(_facts(), "f16", "f16") == 20480
    assert kv.kv_bytes_per_token(_facts(), "f16", "f16") * 8192 == 160 * 1024 ** 2


def test_kv_bytes_per_token_q8_0_is_roughly_half():
    """q8_0 stores 8.5 bits per element: 20 x 512 x 1.0625 = 10880 B."""
    assert kv.kv_bytes_per_token(_facts(), "q8_0", "q8_0") == 10880


def test_kv_at_native_context_fits_the_spec_table():
    per_token = kv.kv_bytes_per_token(_facts(), "f16", "f16")
    assert round(per_token * 262144 / GIB, 1) == 5.0
    per_token_q8 = kv.kv_bytes_per_token(_facts(), "q8_0", "q8_0")
    assert round(per_token_q8 * 262144 / GIB, 1) == 2.7


def test_the_mtp_layer_has_no_main_kv_slot():
    """Was test_undercounting_the_mtp_layer_is_the_9_percent_bug, which asserted
    the nextn block's attention belonged in the main KV cache (11 layers). The
    b11349 load log says 10 -- counting it was a 10% over-count, not a fix. With
    MTP on, that layer gets its own draft context; see mtp_extra_bytes."""
    facts = _facts()
    assert facts.n_attn_layers == 10
    assert 40 not in facts.attn_layer_indices


def test_ssm_state_is_constant_in_context():
    """llama.cpp's conv term is (d_conv-1) x (d_inner + 2 x n_group x d_state):
    conv_width = 4096 + 2*16*128 = 8192; conv = 8192 x 3 = 24576.
    state = 4096 x 128 = 524288.
    per layer = (24576 + 524288) x 4 bytes = 2195456.
    30 SSM layers x 2195456 = 65863680 bytes = 62.8125 MiB."""
    facts = _facts()
    conv_width = 4096 + 2 * 16 * 128
    assert kv.ssm_state_bytes(facts) == 30 * (conv_width * 3 + 4096 * 128) * 4
    assert kv.ssm_state_bytes(facts) == 65863680
    assert round(kv.ssm_state_bytes(facts) / 1024 ** 2) == 63


def test_ssm_state_without_group_count_matches_the_plain_formula():
    """A missing group_count is treated as 0, reducing the conv term to plain
    inner_size x (conv_kernel - 1) -- the formula before Finding 5."""
    facts = _facts(ssm_group_count=None)
    assert kv.ssm_state_bytes(facts) == 30 * (4096 * 3 + 4096 * 128) * 4
    assert round(kv.ssm_state_bytes(facts) / 1024 ** 2) == 61


def test_dense_model_has_no_ssm_state():
    facts = _facts(n_layers=32, attn_layer_indices=tuple(range(32)),
                   ssm_conv_kernel=None, ssm_state_size=None, ssm_inner_size=None,
                   ssm_group_count=None)
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
    assert result.kv_bytes == 10880 * 262144
    assert result.total_bytes == (
        result.weights_bytes + result.mmproj_bytes + result.kv_bytes + result.ssm_bytes
    )
    # 24.0374 weights + 0.8382 mmproj + 2.6562 KV + 0.0613 SSM = 27.5931 GiB.
    # (27.9 before the nextn block was dropped from the main KV cache.)
    # (The spec's 27.8 figure predates SSM state being counted; the SSM figure
    # itself grew slightly under Finding 5's group-count-aware conv term.)
    assert round(result.total_bytes / GIB, 1) == 27.6
    assert result.provenance == "computed"


def test_breakdown_is_unknown_when_kv_dims_missing():
    facts = _facts(total_kv_heads=None)
    result = kv.breakdown(facts, weights_bytes=1, ctx=4096)
    assert result.kv_bytes is None
    assert result.provenance == "unknown"


@pytest.mark.parametrize("name,expected", [
    ("f16", 2.0), ("F16", 2.0), ("bf16", 2.0), ("f32", 4.0),
    ("q8_0", 1.0625), ("q5_1", 0.75), ("q4_0", 0.5625), ("q4_1", 0.625),
    ("nvfp4", 0.5625), ("mxfp4", 0.53125),
    (None, 2.0), ("nonsense", 2.0),
])
def test_cache_bytes_per_elem(name, expected):
    assert kv.cache_bytes_per_elem(name) == expected


@pytest.mark.parametrize("name", [
    "f32", "f16", "bf16", "q8_0", "q6_k", "q5_0", "q5_1", "q4_0", "q4_1",
    "iq4_nl", "nvfp4", "mxfp4", "Q8_0", "q5", "q4", "nonsense", None,
])
def test_cache_bytes_matches_legacy_estimator(name):
    """Guards against Finding 1's row-shifted-table bug recurring: the truth
    layer's cache-byte table must never silently drift from the legacy one."""
    from lcc_core.estimates import _cache_bytes
    assert kv.cache_bytes_per_elem(name) == _cache_bytes(name)


MIB = 1024 ** 2


def _qwen38_27b(**over) -> ArchFacts:
    # read_facts() on Qwen3.8-27B-UD-Q5_K_XL.gguf, 2026-10-10.
    base = dict(
        arch="qwen35", n_layers=65,
        attn_layer_indices=tuple(range(3, 64, 4)),
        total_kv_heads=64, k_len=256, v_len=256, native_ctx=262144,
        n_experts=0, n_experts_used=0, has_mtp=True, n_nextn_layers=1,
        needs_mmproj=True, ssm_conv_kernel=4, ssm_state_size=128,
        ssm_inner_size=6144, ssm_group_count=16, source="tensor-scan",
    )
    base.update(over)
    return ArchFacts(**base)


def test_mtp_extra_matches_llama_cpp_allocation_log():
    """b11349, -c 65536 -ctk/-ctv q8_0, --spec-type draft-mtp --spec-draft-n-max 4:
    main KV 2176 MiB / 16 layers (unchanged), RS 149.62 -> 748.12 MiB,
    draft KV 256.00 MiB (1 layer, f16)."""
    facts = _qwen38_27b()
    assert facts.n_ssm_layers == 48
    assert round(kv.ssm_state_bytes(facts) / MIB, 3) == 149.625
    assert kv.kv_bytes_per_token(facts, "q8_0", "q8_0") * 65536 == 2176 * MIB
    extra = kv.mtp_extra_bytes(facts, ctx=65536, n_max=4)
    assert extra == 256 * MIB + 4 * kv.ssm_state_bytes(facts)
    assert extra / MIB == 854.5  # 256 + 4 x 149.625


def test_mtp_draft_kv_follows_the_draft_cache_type():
    facts = _qwen38_27b()
    f16 = kv.mtp_extra_bytes(facts, ctx=65536, n_max=0)
    q8 = kv.mtp_extra_bytes(facts, ctx=65536, n_max=0, ctk_draft="q8_0", ctv_draft="q8_0")
    assert f16 == 256 * MIB and q8 == 136 * MIB


def test_no_mtp_head_means_no_extra():
    assert kv.mtp_extra_bytes(_qwen38_27b(has_mtp=False, n_nextn_layers=0), ctx=65536) is None
