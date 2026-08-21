import json

# gguf_fixtures lives in this directory; a bare import is required because a
# gitignored vendored checkout (graphify/) ships its own tests package, which
# shadows a `tests.` prefixed import when the whole repo is collected.
from gguf_fixtures import write_minimal_gguf
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
    # delta_pct is (legacy - truth) / truth * 100: positive means legacy reads
    # higher than truth, as it does here.
    assert round(result["delta_pct"]) == 25   # legacy is 25% above truth
    assert result["ctk"] == "f16"
    assert result["ctv"] == "f16"
    # No prior estimates._kv_dims() call resolved exact dims for this model,
    # so the legacy figure came from the KV_FALLBACK_FACTOR heuristic.
    assert result["legacy_exact"] is False

    entry = json.loads(log.read_text().strip())
    assert entry["arch"] == "llama"
    assert entry["source"] == "tensor-scan"
    assert entry["ctk"] == "f16"
    assert entry["ctv"] == "f16"
    assert entry["legacy_exact"] is False


def test_never_raises_on_a_broken_file(tmp_path, monkeypatch):
    """Shadow mode must never break the fit path it observes."""
    broken = tmp_path / "broken.gguf"
    broken.write_bytes(b"NOPE" + b"\x00" * 64)
    monkeypatch.setattr(shadow, "_log_path", lambda: tmp_path / "d.jsonl")
    assert shadow.record_divergence(str(broken), {"ctx_size": 4096}, 10.0) is None
