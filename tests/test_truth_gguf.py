from pathlib import Path
import urllib.request

import pytest

# gguf_fixtures lives in this directory; a bare import is required because a
# gitignored vendored checkout (graphify/) ships its own tests package, which
# shadows a `tests.` prefixed import when the whole repo is collected.
from gguf_fixtures import write_minimal_gguf
from lcc_core.truth.gguf import ArchFacts, read_facts
from lcc_core.truth.gguf import parse_header_bytes, read_facts_remote


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


def test_read_facts_recognises_block_dot_n_tensor_naming(tmp_path):
    """Finding 2: ``block.N.`` naming (not just ``blk.N.``) must be recognised,
    or attention tensors are found but their layer index is lost, falsely
    reporting source == "assumed-dense" instead of "tensor-scan"."""
    attn = [0, 1, 2, 3]
    path = write_minimal_gguf(
        tmp_path / "block_naming.gguf",
        arch="llama",
        n_layer=4,
        attn_layers=attn,
        n_kv_heads=8,
        k_len=128,
        v_len=128,
        tensor_prefix="block",
    )
    facts = read_facts(path)
    assert facts.source == "tensor-scan"
    assert facts.attn_layer_indices == tuple(attn)
    assert facts.total_kv_heads == 32          # 4 layers x 8 KV heads
    assert facts.n_ssm_layers == 0


def test_read_facts_served_from_disk_cache_in_a_fresh_process(tmp_path, monkeypatch):
    """Finding 3: the on-disk cache must survive a 'fresh process' (empty
    in-process memo) so shadow mode doesn't stall ~5.5s on the first estimate
    after every server restart."""
    import lcc_core.truth.gguf as truth_gguf

    path = write_minimal_gguf(
        tmp_path / "diskcache.gguf",
        arch="llama",
        n_layer=4,
        attn_layers=[0, 1, 2, 3],
        n_kv_heads=2,
        k_len=64,
        v_len=64,
    )
    monkeypatch.setattr(truth_gguf, "_facts_cache_file", lambda: tmp_path / "facts_cache.json")

    first = read_facts(path)

    # Simulate a fresh process: the in-process memo is empty, but the on-disk
    # cache written by the first read survives.
    truth_gguf._facts_memo.clear()

    def _boom(*args, **kwargs):
        raise AssertionError("read_facts reopened the file instead of using the disk cache")

    monkeypatch.setattr(truth_gguf.gguf, "GGUFReader", _boom)

    second = read_facts(path)
    assert second == first


def test_read_facts_degrades_to_recompute_on_a_corrupt_disk_cache(tmp_path, monkeypatch):
    """A corrupt or unwritable disk cache must never raise -- it must degrade
    to recomputing from the file."""
    import lcc_core.truth.gguf as truth_gguf

    path = write_minimal_gguf(
        tmp_path / "corrupt.gguf",
        arch="llama",
        n_layer=4,
        attn_layers=[0, 1, 2, 3],
        n_kv_heads=2,
        k_len=64,
        v_len=64,
    )
    cache_file = tmp_path / "facts_cache.json"
    cache_file.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(truth_gguf, "_facts_cache_file", lambda: cache_file)
    truth_gguf._facts_memo.clear()

    facts = read_facts(path)
    assert facts.arch == "llama"
    assert facts.n_layers == 4


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
    assert facts.ssm_group_count == 16


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


def test_read_facts_remote_bounds_the_read(tmp_path, monkeypatch):
    """The remote path must bound its read to max_bytes regardless of HTTP
    status. A 200 response is what a server sends when it ignores the Range
    header and returns the whole body -- calling .read() unbounded there
    would download the entire multi-GB file, defeating the point of this
    function."""
    path = write_minimal_gguf(
        tmp_path / "remote.gguf",
        arch="llama", n_layer=4,
        attn_layers=[0, 1, 2, 3], n_kv_heads=2, k_len=64, v_len=64,
    )
    data = path.read_bytes()
    calls = []

    class FakeResponse:
        status = 200

        def read(self, n=None):
            calls.append(n)
            return data[:n] if n is not None else data

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    facts = read_facts_remote("http://example.invalid/model.gguf", max_bytes=len(data))
    assert facts == read_facts(path)
    assert calls == [len(data)]
    assert calls[0] is not None
