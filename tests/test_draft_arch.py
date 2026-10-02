"""A draft head is a companion, whatever its file is called.

Found 2026-10-02: Muse-Glimmer-30B ships ``dflash-kquant.gguf`` (a DFlash
speculative head, ``general.architecture = dflash``). The name rule only knew
``mtp``/``draft``, so it was registered as a third, same-named "Muse-Glimmer"
profile badged Good at 5.9 GB.
"""
from __future__ import annotations

from types import SimpleNamespace

from lcc_core import profile_registry
from lcc_core.profile_registry import _is_draft_model


def test_dflash_prefix_is_a_companion():
    assert _is_draft_model("models/Muse-Glimmer-30B-GGUF/dflash-kquant.gguf")
    assert _is_draft_model("models/x/eagle3-Q8_0.gguf")


def test_draft_architecture_is_a_companion_whatever_the_name(monkeypatch, tmp_path):
    head = tmp_path / "glimmer-head-q8.gguf"
    head.write_bytes(b"x")
    monkeypatch.setattr(profile_registry, "_gguf_arch", lambda path: "dflash")
    assert _is_draft_model(str(head))


def test_ordinary_architecture_is_not(monkeypatch, tmp_path):
    model = tmp_path / "muse-glimmer-30B-kquant-17gb.gguf"
    model.write_bytes(b"x")
    monkeypatch.setattr(profile_registry, "_gguf_arch", lambda path: "muse-glimmer")
    assert not _is_draft_model(str(model))


def test_unreadable_header_falls_back_to_the_name(monkeypatch, tmp_path):
    model = tmp_path / "plain.gguf"
    model.write_bytes(b"x")
    monkeypatch.setattr(profile_registry, "_gguf_arch", lambda path: None)
    assert not _is_draft_model(str(model))
