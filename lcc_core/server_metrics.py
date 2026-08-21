from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
import urllib.request
from typing import Any

from .server_manager import _find_server, pid_is_running, tail_file

# llama.cpp's server exposes three live endpoints once it's serving:
#   /props   — static JSON about the loaded model + slot config
#   /health  — a one-word status ("ok" / loading / error) plus optional JSON body
#   /metrics — Prometheus text with gauges/counters (KV usage, slots, token rates)
# We pull all three into a single structured snapshot so the dashboard can show
# ground-truth runtime numbers next to the pre-launch estimate.

_HTTP_TIMEOUT = 3.0

# psutil is an optional enhancement for per-process memory (RSS / CPU%). If the
# import fails for any reason, every per-process field returns None instead of
# crashing — the server-level metrics still work fine without it.
try:  # pragma: no cover - exercised only when psutil is missing
    import psutil
except Exception:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


def _get_json(url: str, timeout: float = _HTTP_TIMEOUT) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        import json
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _get_text(url: str, timeout: float = _HTTP_TIMEOUT) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# Prometheus metric lines we care about. Each is a `name{labels} value` line;
# we keep the labels off and parse just the first numeric value we see.
_METRIC_RE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{[^}]*\})?\s+([-+]?[\d.eE+-]+)')

# Map the raw llama.cpp Prometheus metric names to the friendly keys we return.
# These names are stable across llama-server builds (the `llamacpp:` / `llamacpp_`
# prefixes vary by build, so we match by suffix).
_METRIC_ALIASES = {
    "kv_cache_usage_ratio": "kv_cache_usage_ratio",
    "kv_cache_tokens": "kv_cache_tokens",
    "prompt_tokens_seconds": "prompt_tokens_per_second",
    "tokens_predicted_seconds": "predicted_tokens_per_second",
    "prompt_tokens_total": "prompt_tokens_total",
    "tokens_predicted_total": "predicted_tokens_total",
    "active_slots": "slots_active",
    "processing_slots": "slots_processing",
    "requests_in_flight": "requests_in_flight",
    "kv_cache_usage_perc": "kv_cache_usage_ratio",
    "num_requests_running": "requests_in_flight",
    "num_requests_waiting": "requests_waiting",
    "generation_tokens_total": "predicted_tokens_total",
}


# Namespace prefixes llama-server may prepend to its Prometheus metric names,
# across builds: "llamacpp:" (colon form) and "llamacpp_" / "llama_server_"
# (underscore form). Stripped so the alias lookup matches the bare stem.
_METRIC_PREFIXES = ("llamacpp:", "llamacpp_", "llama_server_", "llama_", "vllm:", "vllm_")


def _strip_metric_prefix(name: str) -> str:
    for prefix in _METRIC_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _parse_prometheus(text: str) -> dict[str, float]:
    """Pull the metrics we report from a Prometheus text exposition."""
    out: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _METRIC_RE.match(line)
        if not m:
            continue
        name, raw_value = m.group(1), m.group(2)
        stem = _strip_metric_prefix(name)
        # Match either the full name or the de-namespaced stem against aliases.
        key = _METRIC_ALIASES.get(stem) or _METRIC_ALIASES.get(name)
        if not key or key in out:
            continue
        try:
            out[key] = float(raw_value)
        except ValueError:
            continue
    return out


def _safe(call, default):
    try:
        return call()
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Per-process memory (Stage 2)
#
# A tracked llama-server's actual footprint is split across two sources:
#   - host RAM (RSS): portable via psutil, vendor-agnostic
#   - accelerator VRAM: NVIDIA-only via `nvidia-smi --query-compute-apps`, which
#     attributes used VRAM to each running PID. One shared poll serves every
#     tracked server, TTL-cached behind a lock so a dashboard polling several
#     servers in parallel never fans out into N subprocesses.
# ---------------------------------------------------------------------------

_PROCESS_CACHE_TTL_SECONDS = 2.0
_compute_apps_lock = threading.Lock()
_compute_apps_cache: dict[int, int] | None = None
_compute_apps_cache_ts: float = 0.0
# One-shot graceful disable: when --query-compute-apps isn't supported (older
# driver, no GPU, no NVIDIA), stop trying on every poll.
_compute_apps_unavailable = False

# cpu_percent(interval=None) measures against the *same* Process object's
# previous call, so the handle has to survive across polls. Building a fresh
# psutil.Process each poll always returns the meaningless first-call 0.0.
_process_handles_lock = threading.Lock()
_process_handles: dict[int, Any] = {}


def _process_handle(pid: int) -> tuple[Any, bool]:
    """Return (Process, has_cpu_baseline) reusing one handle per live PID."""
    with _process_handles_lock:
        proc = _process_handles.get(pid)
        # is_running() also compares create_time, so a recycled PID gets a fresh
        # handle rather than a CPU delta against the previous process.
        if proc is not None and proc.is_running():
            return proc, True
        for dead in [known for known, handle in _process_handles.items() if not handle.is_running()]:
            del _process_handles[dead]
        proc = psutil.Process(pid)
        _process_handles[pid] = proc
        return proc, False


def _forget_process(pid: int) -> None:
    with _process_handles_lock:
        _process_handles.pop(pid, None)


def _process_memory(pid: int | None) -> dict[str, int | float | None]:
    """RSS / CPU% for the tracked PID via psutil, or all-None when unavailable."""
    if not pid or psutil is None:
        return {"rss_bytes": None, "cpu_percent": None}
    key = int(pid)
    try:
        proc, has_baseline = _process_handle(key)
        with proc.oneshot():
            mem = proc.memory_info()
            rss = int(getattr(mem, "rss", 0)) or None
            # Always call it, even on the first poll, so psutil's counters get
            # primed; None means "no baseline yet" while a real reading of 0.0
            # is reported as 0.0 rather than swallowed.
            cpu = proc.cpu_percent(interval=None)
        return {"rss_bytes": rss, "cpu_percent": float(cpu) if has_baseline else None}
    except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
        _forget_process(key)
        return {"rss_bytes": None, "cpu_percent": None}


def _query_compute_apps() -> dict[int, int] | None:
    """One nvidia-smi --query-compute-apps poll → {pid: used_memory_bytes}.

    ``used_gpu_memory`` is reported in MiB by nvidia-smi (the default for the
    query API); we convert to bytes here. Returns None when the query isn't
    supported so callers can latch and stop retrying.
    """
    binary = shutil.which("nvidia-smi") or shutil.which("nvidia-smi.exe")
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2.5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    out: dict[int, int] = {}
    for raw_line in result.stdout.splitlines():
        parts = [p.strip() for p in raw_line.split(",")]
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
            mib = int(parts[1])
        except ValueError:
            continue
        out[pid] = mib * 1024 * 1024
    return out


def _compute_apps_vram() -> dict[int, int] | None:
    """Shared, TTL-cached wrapper around :func:`_query_compute_apps`.

    One subprocess call serves every tracked server; lock-guarded so concurrent
    polls don't overlap, with a one-shot disable on the first failure.
    """
    global _compute_apps_cache, _compute_apps_cache_ts, _compute_apps_unavailable
    now = time.monotonic()
    with _compute_apps_lock:
        fresh = (
            _compute_apps_cache is not None
            and (now - _compute_apps_cache_ts) < _PROCESS_CACHE_TTL_SECONDS
        )
        if fresh:
            return _compute_apps_cache
        if _compute_apps_unavailable:
            return None
        snapshot = _query_compute_apps()
        if snapshot is None:
            _compute_apps_unavailable = True
            _compute_apps_cache = None
            return None
        _compute_apps_cache = snapshot
        _compute_apps_cache_ts = now
        return snapshot


def fetch_server_metrics(server_id: str | None = None, mode: str | None = None) -> dict[str, Any]:
    """Live runtime metrics for a tracked llama-server, or an error payload.

    Returns ground-truth KV-cache usage, slot activity, and prompt/decode
    token rates polled from the running server's ``/props``, ``/health``, and
    ``/metrics`` endpoints. When the server isn't reachable (crashed, starting,
    or not a llama.cpp server), returns a structured failure with the stderr
    tail so the caller can show why.
    """
    server = _find_server(server_id, mode)
    if not server:
        return {"success": False, "error": "No tracked server matched the request."}

    pid = server.get("pid")
    host = server.get("host") or "127.0.0.1"
    port = int(server.get("port") or 8080)
    # Resolve wildcard bind targets to localhost so the poll can reach it.
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    base = f"http://{probe_host}:{port}"

    if pid and not pid_is_running(pid):
        return {
            "success": False,
            "error": "Tracked server process is no longer running.",
            "server": server,
            "status": server.get("status"),
            "stderr_tail": tail_file(server.get("stderr_log")),
        }

    is_vllm = server.get("runtime") == "vllm-wsl"
    models_payload = _safe(lambda: _get_json(f"{base}/v1/models"), {}) if is_vllm else {}
    health_text = "ok" if models_payload else _safe(lambda: _get_text(f"{base}/health").strip(), "")
    metrics = _safe(lambda: _get_text(f"{base}/metrics"), "")
    props = _safe(lambda: _get_json(f"{base}/props"), {}) if not is_vllm else {}
    vllm_model = ((models_payload.get("data") or [{}])[0] or {}) if isinstance(models_payload, dict) else {}

    if not health_text and not metrics and not props:
        return {
            "success": False,
            "error": "Server did not respond on /health, /metrics, or /props.",
            "server": server,
            "stderr_tail": tail_file(server.get("stderr_log")),
        }

    parsed_metrics = _parse_prometheus(metrics) if metrics else {}
    # Per-process memory: psutil for RSS/CPU (portable); nvidia-smi --query-
    # compute-apps for GPU attribution (NVIDIA only). Both degrade gracefully
    # to None when unavailable — never block the server-level snapshot.
    proc_mem = _process_memory(server.get("pid"))
    gpu_apps = _safe(lambda: _compute_apps_vram(), None) or {}
    pid_int = int(server["pid"]) if server.get("pid") else None
    gpu_used_bytes = gpu_apps.get(pid_int) if pid_int is not None else None
    return {
        "success": True,
        "server": server,
        "health": health_text or "unknown",
        "props": {
            "model_name": vllm_model.get("id") or props.get("model_name") or props.get("default_generation_settings", {}).get("model"),
            "context_length": props.get("total_slots"),
            "chat_template": props.get("chat_template"),
            "n_ctx": vllm_model.get("max_model_len") or props.get("n_ctx"),
            "build_info": "vLLM" if is_vllm else props.get("build_info"),
        },
        "metrics": parsed_metrics,
        "process": {
            "rss_bytes": proc_mem["rss_bytes"],
            "cpu_percent": proc_mem["cpu_percent"],
            "gpu_used_bytes": gpu_used_bytes,
        },
        "summary": {
            "kv_cache_usage_ratio": parsed_metrics.get("kv_cache_usage_ratio"),
            "kv_cache_tokens": parsed_metrics.get("kv_cache_tokens"),
            "slots_active": parsed_metrics.get("slots_active"),
            "slots_processing": parsed_metrics.get("slots_processing"),
            "prompt_tokens_per_second": parsed_metrics.get("prompt_tokens_per_second"),
            "predicted_tokens_per_second": parsed_metrics.get("predicted_tokens_per_second"),
        },
    }
