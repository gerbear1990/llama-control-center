from __future__ import annotations

import json
import re
import shlex
from pathlib import Path, PureWindowsPath
from typing import Any

from .llama_args import LaunchCommand


WINDOWS_PATH_RE = re.compile(r"^(?P<drive>[A-Za-z]):[\\/](?P<rest>.*)$")


def windows_to_wsl_path(value: str) -> str:
    """Convert a local Windows path to the standard WSL DrvFS path."""

    match = WINDOWS_PATH_RE.match(value)
    if not match:
        return value
    drive = match.group("drive").lower()
    rest = str(PureWindowsPath(match.group("rest"))).replace("\\", "/")
    return f"/mnt/{drive}/{rest}"


def build_wsl_vllm_args(
    wsl_binary: str,
    distro: str,
    venv_path: str,
    model_path: str,
    params: dict[str, Any],
    pidfile: str,
) -> LaunchCommand:
    """Build an attached WSL command for a vLLM OpenAI-compatible server."""

    warnings: list[str] = []
    model = windows_to_wsl_path(model_path)
    executable = f"{venv_path.rstrip('/')}/bin/vllm"
    host = str(params.get("host") or "127.0.0.1")
    port = int(params.get("port") or 8000)
    alias = str(params.get("alias") or Path(model_path).name)
    # ctx_size is the shared LCC UI field; let an interactive override win over
    # the saved vLLM-specific alias.
    max_model_len = int(params.get("ctx_size") or params.get("max_model_len") or 4096)
    gpu_util = float(params.get("gpu_memory_utilization", 0.9))
    max_num_seqs = int(params.get("max_num_seqs", 32))
    max_num_batched_tokens = int(params.get("max_num_batched_tokens", 2048))

    serve_args = [
        executable,
        "serve",
        model,
        "--host",
        host,
        "--port",
        str(port),
        "--served-model-name",
        alias,
        "--max-model-len",
        str(max_model_len),
        "--gpu-memory-utilization",
        str(gpu_util),
        "--max-num-seqs",
        str(max_num_seqs),
        "--max-num-batched-tokens",
        str(max_num_batched_tokens),
    ]
    if params.get("trust_remote_code", True):
        serve_args.append("--trust-remote-code")
    if params.get("enable_auto_tool_choice", True):
        serve_args.append("--enable-auto-tool-choice")
    tool_parser = str(params.get("tool_call_parser") or "").strip()
    if tool_parser:
        serve_args.extend(["--tool-call-parser", tool_parser])
    reasoning_parser = str(params.get("reasoning_parser") or "").strip()
    if reasoning_parser:
        serve_args.extend(["--reasoning-parser", reasoning_parser])
    if params.get("enable_mtp", False):
        speculative = {
            "method": "mtp",
            "num_speculative_tokens": int(params.get("mtp_speculative_tokens", 2)),
        }
        serve_args.extend(["--speculative-config", json.dumps(speculative, separators=(",", ":"))])

    extra = params.get("vllm_extra_args") or []
    if isinstance(extra, str):
        warnings.append("vllm_extra_args must be a list; the string value was ignored.")
    else:
        serve_args.extend(str(value) for value in extra)

    quoted_command = " ".join(shlex.quote(arg) for arg in serve_args)
    quoted_pidfile = shlex.quote(pidfile)
    shell_command = (
        "set -euo pipefail; "
        "export CUDA_HOME=/usr/local/cuda; "
        "export PATH=/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin; "
        "export LD_LIBRARY_PATH=/usr/local/cuda/lib64; "
        "mkdir -p /tmp/lcc-vllm; "
        f"echo $$ > {quoted_pidfile}; "
        f"trap 'rm -f {quoted_pidfile}' EXIT; "
        f"exec {quoted_command}"
    )
    return LaunchCommand(
        argv=[wsl_binary, "-d", distro, "--", "bash", "-lc", shell_command],
        cwd=None,
        warnings=warnings,
    )


__all__ = ["build_wsl_vllm_args", "windows_to_wsl_path"]
