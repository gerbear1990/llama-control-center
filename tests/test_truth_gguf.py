from pathlib import Path

import pytest

from tests.gguf_fixtures import write_minimal_gguf
from lcc_core.truth.gguf import ArchFacts, read_facts
from lcc_core.truth.gguf import parse_header_bytes


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
