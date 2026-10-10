"""The fit badge must say when it is guessing, and never call a missing file Good.

Found 2026-10-02 by launching Qwen3.8-27B through LCC: the profiles list showed
"Near Limit, 45.6 GB" on a cold header cache and "Good, 24.2 GB" once the header
had been read — measured was 22.7 GB. The guess was presented as a verdict.
"""
from __future__ import annotations

from lcc_core import estimates

HW = {"primary_gpu": {"name": "NVIDIA GeForce RTX 5090", "vram_total_bytes": 32 * 1024**3},
      "memory": {"total_bytes": 64 * 1024**3}}
PARAMS = {"ctx_size": 131072, "cache_type_k": "q4_0", "cache_type_v": "q4_0", "gpu_layers": 999}


def test_cold_header_is_reported_as_heuristic(tmp_path, monkeypatch):
    monkeypatch.setattr(estimates, "_gguf_meta", lambda path, parse: (None, None, None, None))
    model = {"path": str(tmp_path / "m.gguf"), "params_b": 27.0, "size_bytes": 20 * 1024**3}
    fit = estimates.estimate_memory_fit(PARAMS, model, HW)
    assert fit["basis"] == "heuristic"
    assert any("rough" in w.lower() for w in fit["warnings"])


def test_known_kv_dims_are_reported_as_exact():
    model = {"path": "x.gguf", "params_b": 27.0, "size_bytes": 20 * 1024**3, "kv_dims": [68, 256, 256]}
    fit = estimates.estimate_memory_fit(PARAMS, model, HW)
    assert fit["basis"] == "exact"
    assert not any("rough" in w.lower() for w in fit["warnings"])


def test_missing_model_file_is_never_good():
    profile = {"mode": "gone", "params": PARAMS, "model": None, "missing": ["model"], "launchable": False}
    [item] = estimates.enrich_profiles_with_fit_status([profile], HW)
    assert item["fit_status"]["status"] == "missing"
    assert item["fit_status"]["label"] == "Missing file"


def test_missing_draft_alone_does_not_mark_the_model_missing():
    model = {"path": "x.gguf", "params_b": 27.0, "size_bytes": 20 * 1024**3, "kv_dims": [68, 256, 256]}
    profile = {"mode": "d", "params": PARAMS, "model": model, "missing": ["draft_model"], "launchable": False}
    [item] = estimates.enrich_profiles_with_fit_status([profile], HW)
    assert item["fit_status"]["status"] != "missing"


def test_prewarm_reads_each_existing_gguf_once_and_never_raises(tmp_path, monkeypatch):
    good = tmp_path / "a.gguf"
    good.write_bytes(b"x")
    bad = tmp_path / "b.gguf"
    bad.write_bytes(b"x")
    (tmp_path / "c.safetensors").write_bytes(b"x")
    seen: list[tuple[str, bool]] = []

    def fake(path, parse):
        seen.append((path, parse))
        if path.endswith("b.gguf"):
            raise ValueError("corrupt header")
        return (None, None, None, None)

    monkeypatch.setattr(estimates, "_gguf_meta", fake)
    paths = [str(good), str(bad), str(good), str(tmp_path / "c.safetensors"), str(tmp_path / "gone.gguf"), None]
    assert estimates.prewarm_gguf_meta(paths) == 1
    assert seen == [(str(good), True), (str(bad), True)]
