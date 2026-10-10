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


# b11349 also turned --draft-max/--draft-min into hard errors ("the argument has
# been removed. use --spec-draft-n-max"). The old names still appear in --help on
# that "removed" line, so the help set contains both -- only the new name decides.
SPEC_NEW = NEW | {"--model-draft", "--spec-type", "--spec-draft-n-max", "--spec-draft-n-min",
                  "--draft-max", "--draft-min"}


def test_new_build_uses_spec_draft_n_max(monkeypatch):
    argv = _argv(monkeypatch, SPEC_NEW, {"draft_model": "d.gguf", "spec_draft_n_max": 4, "draft_min": 1}).argv
    assert argv[argv.index("--spec-draft-n-max") + 1] == "4"
    assert argv[argv.index("--spec-draft-n-min") + 1] == "1"
    assert "--draft-max" not in argv and "--draft-min" not in argv


def test_old_build_keeps_draft_max(monkeypatch):
    old = OLD | {"--model-draft", "--spec-type", "--draft-max", "--draft-min"}
    argv = _argv(monkeypatch, old, {"draft_model": "d.gguf", "spec_draft_n_max": 4}).argv
    assert argv[argv.index("--draft-max") + 1] == "4"


def test_embedded_mtp_gets_draft_tuning_without_a_draft_file(monkeypatch):
    # Qwen3.8 carries its MTP head in the main GGUF: --spec-type draft-mtp and no
    # --model-draft. n-max must still reach the server.
    argv = _argv(monkeypatch, SPEC_NEW, {"spec_type": "draft-mtp", "spec_draft_n_max": 4}).argv
    assert "--model-draft" not in argv
    assert argv[argv.index("--spec-type") + 1] == "draft-mtp"
    assert argv[argv.index("--spec-draft-n-max") + 1] == "4"


def test_ngram_spec_type_gets_no_draft_tuning(monkeypatch):
    argv = _argv(monkeypatch, SPEC_NEW, {"spec_type": "ngram-cache", "spec_draft_n_max": 4}).argv
    assert "--spec-draft-n-max" not in argv
