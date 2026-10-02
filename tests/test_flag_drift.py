"""Launch flags must follow the installed binary, not the build LCC was written for.

Found 2026-10-02: llama-server was upgraded b10752 -> b11349 mid-session. The new
build removed --mmap/--no-mmap in favour of --load-mode, LCC still emitted
--mmap, and every launch died with "invalid argument: --mmap" -- surfacing in
the UI only as "did not become ready before timeout".
"""
from __future__ import annotations

from lcc_core import llama_args
from lcc_core.llama_args import build_llama_server_args

OLD = frozenset({"-m", "--host", "--port", "--mmap", "--no-mmap", "--metrics", "--jinja"})
NEW = frozenset({"-m", "--host", "--port", "--load-mode", "--metrics", "--jinja"})


def _argv(monkeypatch, flags, params):
    monkeypatch.setattr(llama_args, "supported_flags", lambda binary: flags)
    return build_llama_server_args("llama-server", "m.gguf", {"gpu_layers": 999, **params})


def test_old_build_keeps_mmap_flags(monkeypatch):
    assert "--mmap" in _argv(monkeypatch, OLD, {}).argv
    assert "--no-mmap" in _argv(monkeypatch, OLD, {"mmap": False}).argv


def test_new_build_uses_load_mode(monkeypatch):
    on = _argv(monkeypatch, NEW, {}).argv
    off = _argv(monkeypatch, NEW, {"mmap": False}).argv
    assert "--mmap" not in on and "--load-mode" not in on  # auto == mmap
    assert off[off.index("--load-mode") + 1] == "none"
    assert "--no-mmap" not in off


def test_unknown_help_falls_back_to_legacy_flags(monkeypatch):
    assert "--mmap" in _argv(monkeypatch, None, {}).argv


def test_flags_the_binary_does_not_know_are_warned_about(monkeypatch):
    cmd = _argv(monkeypatch, frozenset({"-m", "--host", "--port", "--load-mode"}), {})
    assert any("--metrics" in w and "not recognised" in w for w in cmd.warnings)


def test_help_parsing_reads_every_flag_spelling():
    text = (
        "-lm,   --load-mode MODE                 model loading mode (default: auto)\n"
        "--slots, --no-slots                     expose slots monitoring endpoint\n"
        "-m,    --model FNAME                    model path\n"
    )
    flags = llama_args._parse_help_flags(text)
    assert {"--load-mode", "-lm", "--slots", "--no-slots", "-m", "--model"} <= flags
