from __future__ import annotations

import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from functools import lru_cache
from typing import Any


@dataclass
class LaunchCommand:
    argv: list[str]
    cwd: str | None
    warnings: list[str] = field(default_factory=list)

    @property
    def command_line(self) -> str:
        return subprocess.list2cmdline(self.argv)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["command_line"] = self.command_line
        return data


# Flags come from the installed binary's --help, not from the build this code
# was written against: llama-server renames flags between builds (b11349
# dropped --mmap/--no-mmap for --load-mode) and an unknown flag makes it exit
# before it listens, which the UI can only report as a startup timeout.
_HELP_FLAG_RE = re.compile(r"(?<![\w-])(--?[A-Za-z][\w-]*)")


def _parse_help_flags(text: str) -> frozenset[str]:
    return frozenset(_HELP_FLAG_RE.findall(text or ""))


@lru_cache(maxsize=8)
def _supported_flags_cached(binary: str, size: int, mtime: int) -> frozenset[str] | None:
    try:
        result = subprocess.run(
            [binary, "--help"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    flags = _parse_help_flags((result.stdout or "") + (result.stderr or ""))
    # A real llama-server --help lists hundreds of flags; anything sparse is
    # not a help page we can trust to veto flags.
    return flags if len(flags) > 50 else None


def supported_flags(binary: str) -> frozenset[str] | None:
    """Flags the llama-server at ``binary`` accepts, or None if unknown.

    Cached per (path, size, mtime), so an in-place upgrade is picked up on the
    next launch without restarting the dashboard.
    """
    try:
        st = os.stat(binary)
    except OSError:
        return None
    return _supported_flags_cached(str(binary), st.st_size, int(st.st_mtime))


# Accepted values of llama.cpp's --spec-type. Anything else makes llama-server
# exit before it listens, so this set is validated against, not guessed at.
#
# Verified against llama-server build 10472, upstream commit 60eeeb608
# (2026-08-17), common/arg.cpp: common_speculative_types_from_names().
# Re-check on a llama.cpp upgrade -- the previous six-value set here was
# correct for the April source clone in tools/llama.cpp-source and silently
# fell behind when the binary gained the draft-* family.
#
# The draft-* types pair with a draft model (--model-draft / --spec-draft-model
# or a sidecar the draft repo ships); the ngram-* types need no draft model.
# Upstream does NOT treat the two flags as mutually exclusive: given a draft
# model and no --spec-type it infers the type from the sidecar or the draft
# GGUF's metadata, and an explicit --spec-type overrides that inference.
SPEC_TYPES = {
    "none",
    "draft-simple", "draft-eagle3", "draft-mtp", "draft-dflash", "draft-dspark",
    "ngram-simple", "ngram-map-k", "ngram-map-k4v", "ngram-mod", "ngram-cache",
}


def _bool_on(value: Any) -> str:
    return "on" if bool(value) else "off"


def normalize_gpu_layers(value: Any) -> int | None:
    """Coerce a gpu_layers param to an int. None/absent -> None (omit flag).

    Accepts the "offload everything" words other parts of the app already use
    ('all'/'auto'/'max', see estimates._layer_fraction and fit.parse_fitted_args)
    and float-ish strings like '32.0'. Unknown non-numeric -> 999 (all).
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"all", "auto", "max"}:
        return 999
    try:
        return int(float(text))
    except ValueError:
        return 999


def _add_optional(args: list[str], flag: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    args.extend([flag, str(value)])


# Default CUDA flash-attention only instantiates matched K/V types
# (f16/f16, bf16/bf16, q8_0/q8_0, q4_0/q4_0). A mismatched pair returns
# BEST_FATTN_KERNEL_NONE and llama.cpp silently runs attention on the CPU.
_KV_COERCE_SKIP_BACKENDS = {"cpu", "metal"}


def normalize_kv_cache_pair(params: dict[str, Any]) -> tuple[Any, Any, str | None]:
    """Return ``(k, v, warning)``. Coerce V to K when a CUDA FA kernel is missing.

    CPU and Metal are left alone: they do not hit the CUDA dispatcher that
    drops mismatched pairs onto the host.
    """
    cache_k = params.get("cache_type_k")
    cache_v = params.get("cache_type_v")
    k_text = str(cache_k).strip().lower() if cache_k not in (None, "") else ""
    v_text = str(cache_v).strip().lower() if cache_v not in (None, "") else ""
    if not k_text or not v_text or k_text == v_text:
        return cache_k, cache_v, None
    backend = str(params.get("acceleration_backend") or "").strip().lower()
    if backend in _KV_COERCE_SKIP_BACKENDS:
        return cache_k, cache_v, None
    gpu_layers = normalize_gpu_layers(params.get("gpu_layers"))
    if gpu_layers == 0:
        return cache_k, cache_v, None
    warning = (
        f"Mismatched KV cache {k_text}/{v_text} has no CUDA flash-attn kernel; "
        f"llama.cpp would run prompt eval on the CPU. Launched as {k_text}/{k_text}."
    )
    return k_text, k_text, warning


def build_llama_server_args(
    llama_server: str,
    model_path: str,
    params: dict[str, Any],
    extra_args: list[str] | None = None,
) -> LaunchCommand:
    """Build a modern llama-server argv list from normalized profile params."""

    warnings: list[str] = []
    cache_k, cache_v, kv_warning = normalize_kv_cache_pair(params)
    if kv_warning:
        warnings.append(kv_warning)
        params = {**params, "cache_type_k": cache_k, "cache_type_v": cache_v}
    flags = supported_flags(llama_server)
    args = [
        llama_server,
        "-m",
        model_path,
        "--host",
        str(params.get("host", "127.0.0.1")),
        "--port",
        str(int(params.get("port", 8080))),
        "--alias",
        str(params.get("alias", Path(model_path).stem)),
    ]

    mapping = [
        ("ctx_size", "--ctx-size"),
        ("threads", "--threads"),
        ("threads_batch", "--threads-batch"),
        ("batch_size", "--batch-size"),
        ("ubatch_size", "--ubatch-size"),
        ("cache_type_k", "--cache-type-k"),
        ("cache_type_v", "--cache-type-v"),
        ("cache_ram_mib", "--cache-ram"),
        ("cache_reuse", "--cache-reuse"),
        ("slot_prompt_similarity", "--slot-prompt-similarity"),
        ("reasoning_budget", "--reasoning-budget"),
        ("n_predict", "--predict"),
        ("seed", "--seed"),
        ("temperature", "--temp"),
        ("top_k", "--top-k"),
        ("top_p", "--top-p"),
        ("min_p", "--min-p"),
        ("repeat_last_n", "--repeat-last-n"),
        ("repeat_penalty", "--repeat-penalty"),
        ("presence_penalty", "--presence-penalty"),
        ("frequency_penalty", "--frequency-penalty"),
    ]
    for key, flag in mapping:
        _add_optional(args, flag, params.get(key))

    gpu_layers = 0 if str(params.get("acceleration_backend", "")).lower() == "cpu" else normalize_gpu_layers(params.get("gpu_layers"))
    if gpu_layers is not None:
        args.extend(["--gpu-layers", "all" if gpu_layers >= 999 else str(gpu_layers)])

    # llama.cpp's threadpool busy-waits for work (--poll defaults to 50), so the
    # worker threads keep spinning at 100% between batches and an *idle* server
    # pegs `--threads` cores forever. With the model offloaded there's nothing for
    # them to do, so default polling off; callers can still set `poll` explicitly.
    poll = params.get("poll")
    if poll is None:
        poll = 50 if gpu_layers in (None, 0) else 0
    args.extend(["--poll", str(int(poll))])

    args.extend(["--flash-attn", _bool_on(params.get("flash_attn", True))])
    args.extend(["--reasoning", _bool_on(params.get("reasoning", False))])
    # --jinja is a presence flag (no on/off value). It makes llama.cpp use the
    # model's own chat template + tool-call parser; without it, tool results are
    # injected wrong and tool-capable models loop the same call forever.
    if params.get("jinja"):
        args.append("--jinja")
    # /metrics is off by default in llama-server; without it the dashboard's
    # metrics panel (KV usage, slots, token rates) is empty for every server
    # LCC launches. Prometheus text on localhost costs nothing.
    args.append("--metrics")
    args.append("--kv-offload" if params.get("kv_offload", True) else "--no-kv-offload")
    args.append("--op-offload" if params.get("op_offload", True) else "--no-op-offload")

    device = params.get("device", params.get("cuda_device"))
    if device not in (None, "", "auto"):
        args.extend(["--device", str(device)])
    if flags is not None and "--load-mode" in flags and "--mmap" not in flags:
        # --load-mode defaults to auto (mmap unless the device can't), so only
        # opting out needs a flag.
        if not params.get("mmap", True):
            args.extend(["--load-mode", "none"])
    elif params.get("mmap", True):
        args.append("--mmap")
    else:
        args.append("--no-mmap")
    if params.get("embedding", False):
        args.append("--embedding")

    draft_model = str(params.get("draft_model", "")).strip()
    spec_type = str(params.get("spec_type", "")).strip()
    if draft_model:
        args.extend(["--model-draft", draft_model])
    # Draft tuning applies to embedded heads too (draft-mtp with no draft file),
    # so it follows any draft-* type, not just a --model-draft.
    if draft_model or any(part.strip().startswith("draft-") for part in spec_type.split(",")):
        # b11349 renamed --draft-max/--draft-min to --spec-draft-n-max/-n-min and
        # made the old names hard errors. The old names still appear in --help
        # (as "has been removed"), so test for the new name, never the old one.
        # Unknown help falls back to legacy names, like --mmap above.
        modern = flags is not None and "--spec-draft-n-max" in flags
        draft_max = params.get("spec_draft_n_max", params.get("draft_max"))
        if draft_max is not None:
            args.extend(["--spec-draft-n-max" if modern else "--draft-max", str(draft_max)])
        draft_min = params.get("spec_draft_n_min", params.get("draft_min"))
        if draft_min is not None:
            args.extend(["--spec-draft-n-min" if modern else "--draft-min", str(draft_min)])
        if "draft_p_min" in params:
            args.extend(["--draft-p-min", str(params["draft_p_min"])])
    if spec_type:
        # Upstream takes a comma-separated list and appends each name to
        # params.speculative.types, so emit the whole valid list rather than a
        # single value. Emitted alongside --model-draft too: the two are
        # independent upstream, and an explicit type overrides the inference
        # llama.cpp would otherwise make from the draft sidecar/GGUF metadata.
        requested = [part.strip() for part in spec_type.split(",")]
        accepted = [part for part in requested if part and part in SPEC_TYPES]
        rejected = [part for part in requested if part and part not in SPEC_TYPES]
        if accepted:
            args.extend(["--spec-type", ",".join(accepted)])
        for part in rejected:
            warnings.append(f"spec_type '{part}' is not a supported value; it was not emitted.")

    tensor_overrides = params.get("tensor_overrides") or params.get("override_tensors") or params.get("ot")
    if tensor_overrides:
        if isinstance(tensor_overrides, list):
            for override in tensor_overrides:
                args.extend(["-ot", str(override)])
        else:
            args.extend(["-ot", str(tensor_overrides)])

    if extra_args:
        args.extend(extra_args)

    if flags is not None:
        for token in args[1:]:
            if token.startswith("-") and not re.match(r"-\d", token) and token not in flags:
                warnings.append(
                    f"{token} is not recognised by this llama-server build; "
                    "it will likely refuse to start."
                )

    return LaunchCommand(argv=args, cwd=str(Path(llama_server).parent), warnings=warnings)
