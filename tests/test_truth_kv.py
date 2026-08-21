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
    # 24.0374 weights + 0.8382 mmproj + 2.9219 KV + 0.0600 SSM = 27.8575 GiB.
    # (The spec's 27.8 figure predates SSM state being counted.)
    assert round(result.total_bytes / GIB, 1) == 27.9
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
