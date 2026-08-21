from __future__ import annotations

import csv
import json
import os
import shutil
import socket
import shlex
import subprocess
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backends import detect_llama_cpp, detect_runtime
from .config import AppConfig
from .hardware import _windows_memory_info, _posix_memory_info
from .llama_args import LaunchCommand, build_llama_server_args
from .manifest import ManifestReadError
from .paths import cache_dir, find_project_root, is_windows
from .profile_resolver import ResolvedProfile, resolve_profiles
from .vllm_args import build_wsl_vllm_args

# psutil is a declared dependency; treat as hard for process introspection
# but keep defensive checks in case of partial envs.
try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None  # type: ignore[assignment]


STATE_FILENAME = "servers.json"
LOG_DIRNAME = "logs"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_path() -> Path:
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root / STATE_FILENAME


def log_dir() -> Path:
    path = cache_dir() / LOG_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_state() -> dict[str, Any]:
    path = state_path()
    if not path.is_file():
        return {"servers": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"servers": []}


def write_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def pid_is_running(pid: int | None) -> bool:
    """Return True if a process with the given PID is currently running.

    Prefers psutil (robust, cross-platform, no output parsing). Falls back
    to OS signals + platform-specific checks (tasklist on Windows, /proc
    zombie detection on Linux).
    """
    if not pid:
        return False
    p = int(pid)
    if psutil is not None:
        try:
            proc = psutil.Process(p)
            # status() will raise NoSuchProcess if gone
            status = proc.status()
            # Treat zombies as not-running for our purposes (matches prior Linux logic)
            if status == psutil.STATUS_ZOMBIE:
                return False
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False
        except Exception:
            # Fall through to legacy checks on unexpected psutil errors
            pass

    if is_windows():
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {p}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return str(p) in result.stdout

    try:
        os.kill(p, 0)
    except OSError:
        return False
    # Linux zombie detection (best effort)
    try:
        with open(f"/proc/{p}/stat", encoding="ascii") as f:
            return f.read().rpartition(")")[2].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def _wait_gone(pid: int, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not pid_is_running(pid):
            return True
        time.sleep(0.25)
    return False


def tail_file(path: str | Path | None, lines: int = 120) -> str:
    if not path:
        return ""
    file_path = Path(path)
    if not file_path.is_file():
        return ""
    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError as exc:
        return f"Could not read {file_path}: {exc}"


# Attempt to bind our own socket to ``host:port``. With ``SO_REUSEADDR`` off
# (which we explicitly don't set on the probe), this fails fast with
# ``EADDRINUSE``/``WSAEADDRINUSE`` when anything else is bound, and
# succeeds when nothing is. Closing the probe socket immediately releases
# the address — the kernel doesn't keep it bound because we never call
# ``listen()`` on it.
#
# Why not a TCP connect probe? Exhausting the listener's accept() backlog
# on a busy port can make subsequent probes return ``ECONNREFUSED``,
# which a connect-based probe would misinterpret as "free". The bind
# probe doesn't have that failure mode.
MAX_PORT = 65535


def _is_port_free(host: str, port: int, *, timeout: float = 0.6) -> bool:
    # Upper bound matters as much as the lower one: bind() raises
    # OverflowError (not OSError) above 65535, which the except below would
    # not catch. _next_free_port can reach here with 65536 by bumping past a
    # dynamic range that ends at exactly MAX_PORT.
    if not port or port <= 0 or port > MAX_PORT:
        return False
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # No SO_REUSEADDR — we WANT bind() to fail on a busy port.
        probe.settimeout(timeout)
        probe.bind((host, int(port)))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def _next_free_port(host: str, start: int, *, max_tries: int = 50) -> int | None:
    """Find the next free TCP port at or above ``start`` by probing each.

    On Windows, ``start`` is bumped past any ``netsh int ipv4 show
    excludedportrange protocol=tcp`` block it happens to fall inside; that's
    the failure mode that caught the default llama-server ports 8080/8081
    on hosts where Hyper-V / Docker / a previous netsh invocation reserved
    those ranges. Subsequent probes use the normal one-by-one walk.

    Returns ``None`` when every candidate in the [start, start+max_tries)
    window is busy; callers should fall back to letting llama-server
    report its own bind error rather than suggesting an unbounded scan.
    """
    start = int(start)
    if is_windows():
        for rng in _windows_excluded_port_ranges():
            if rng["start"] <= start <= rng["end"]:
                start = rng["end"] + 1
                break
        # Also treat the dynamic range as reserved.
        dyn = _windows_dynamic_port_range()
        if dyn and dyn["start"] <= start <= dyn["end"]:
            start = dyn["end"] + 1
    for offset in range(max_tries):
        candidate = start + offset
        if candidate > MAX_PORT:
            # Walked off the end of the port space. Windows' dynamic range
            # routinely ends at exactly 65535, so bumping past it puts `start`
            # at 65536 before the first probe.
            return None
        if _is_port_free(host, candidate):
            return candidate
    return None


# Best-effort lookup of ports Windows will refuse to bind for our user.
# Returns a *list* of ``{start, end}`` ranges (both inclusive) covering
# every excluded range `netsh int ipv4 show excludedportrange protocol=tcp`
# reports. ``get_dynamicportrange`` is less reliable on hosts where
# Hyper-V / Docker / a previous netsh command has carved out specific
# sub-ranges; the exclusion list is the actual source of truth.
def _windows_excluded_port_ranges() -> list[dict[str, int]]:
    ranges: list[dict[str, int]] = []
    try:
        result = subprocess.run(
            ["netsh", "int", "ipv4", "show", "excludedportrange",
             "protocol=tcp"],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ranges
    if result.returncode != 0 or not result.stdout:
        return ranges
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith(("protocol", "start port",
                                                "----", "*-")):
            continue
        parts = line.split()
        # Lines look like: "  8055        8154" — whitespace-separated ints.
        if len(parts) < 2:
            continue
        try:
            start, end = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if end < start:
            continue
        ranges.append({"start": start, "end": end})
    return ranges


def _windows_dynamic_port_range() -> dict[str, int] | None:
    try:
        result = subprocess.run(
            ["netsh", "int", "ipv4", "show", "dynamicportrange", "tcp"],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    start: int | None = None
    count: int | None = None
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        low = line.lower()
        if low.startswith("start port"):
            try:
                start = int(line.split(":", 1)[1].strip())
            except (IndexError, ValueError):
                pass
        elif low.startswith("number of ports"):
            try:
                count = int(line.split(":", 1)[1].strip())
            except (IndexError, ValueError):
                pass
    if start is None or count is None:
        return None
    return {"start": start, "end": start + count - 1}


def _is_port_reserved_on_windows(port: int) -> bool:
    """True when ``port`` falls inside *any* Windows-blessed reserved range.

    Cheap path — used by the pre-launch port probe to distinguish a real
    EADDRINUSE from an EACCES that the kernel returns for reserved ports.
    """
    if not is_windows() or not port or port <= 0:
        return False
    port = int(port)
    for rng in _windows_excluded_port_ranges():
        if rng["start"] <= port <= rng["end"]:
            return True
    dyn = _windows_dynamic_port_range()
    if dyn and dyn["start"] <= port <= dyn["end"]:
        return True
    return False


def _probe_port(host: str, port: int, *, timeout: float = 0.6) -> dict[str, Any]:
    """Bind-probe that returns WHY a port is unusable.

    Three outcomes:
      - ``{"free": True}`` — caller can use ``port``.
      - ``{"free": False, "reason": "reserved", "range": {start,end}}`` —
        Windows refused bind for permission reasons (EACCES). The
        offending range is reported so the UI can suggest a port outside
        it.
      - ``{"free": False, "reason": "in_use"}`` — another socket owns it
        (real EADDRINUSE). The caller should run ``_port_in_use_info`` to
        fill in pid/process_name when needed for the UI.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(timeout)
        probe.bind((host, int(port)))
        return {"free": True}
    except PermissionError:
        # Linux: EACCES means low ports (1-1023) without privileges.
        # Windows: EACCES means the port is in a kernel-managed range
        # (either the dynamic range or a netsh excludedportrange block).
        if is_windows():
            port_int = int(port)
            for rng in _windows_excluded_port_ranges():
                if rng["start"] <= port_int <= rng["end"]:
                    return {"free": False, "reason": "reserved",
                            "range": rng}
            dyn = _windows_dynamic_port_range()
            if dyn and dyn["start"] <= port_int <= dyn["end"]:
                return {"free": False, "reason": "reserved", "range": dyn}
        return {"free": False, "reason": "in_use"}
    except OSError:
        return {"free": False, "reason": "in_use"}
    finally:
        probe.close()


# Best-effort lookup of which process is listening on ``host:port``.
# Returns a dict ``{pid, process_name}`` or ``None`` when nothing bound or
# the platform tools (lsof / netstat) aren't available.
def _port_in_use_info(host: str, port: int) -> dict[str, Any] | None:
    """Return info about the process listening on host:port if any.

    Strongly prefers psutil.net_connections() for robust, locale-independent,
    IPv4/IPv6 aware results (no fragile text parsing of netstat/lsof).
    Falls back to subprocess parsing when psutil is unavailable.
    """
    if not port:
        return None
    p = int(port)
    h = host or "127.0.0.1"

    if psutil is not None:
        try:
            conns = psutil.net_connections(kind="tcp")
            for conn in conns:
                if conn.status != psutil.CONN_LISTEN:
                    continue
                # conn.laddr can be (ip, port) or addr obj
                laddr = conn.laddr
                lport = laddr.port if hasattr(laddr, "port") else laddr[1]
                if lport != p:
                    continue
                lip = str(laddr.ip if hasattr(laddr, "ip") else laddr[0])
                # Match requested host or common wildcards
                if lip in ("", "0.0.0.0", "::", h, "127.0.0.1", "::1"):
                    pid = conn.pid
                    if pid:
                        name = None
                        try:
                            name = psutil.Process(pid).name()
                        except Exception:
                            name = _tasklist_name(str(pid)) if is_windows() else _ps_name(pid)
                        return {"pid": int(pid), "process_name": name}
            return None
        except Exception:
            # fall through to legacy parsing
            pass

    # Legacy fallback (text parsing) — improved but still best-effort
    try:
        if is_windows():
            result = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True, timeout=3, check=False,
            )
            if result.returncode != 0:
                return None
            target = f":{int(p)}"
            for raw_line in result.stdout.splitlines():
                line = raw_line.strip()
                if not line.startswith("TCP"):
                    continue
                # netstat lines: Proto Local Foreign State PID
                parts = line.split()
                if len(parts) < 5:
                    continue
                local = parts[1]
                state = parts[3]
                pid_str = parts[4]
                if state != "LISTENING":
                    continue
                if target not in local:
                    continue
                # Also consider host-specific match if provided
                if h not in ("127.0.0.1", "0.0.0.0") and h not in local:
                    continue
                if not pid_str.isdigit():
                    continue
                name = _tasklist_name(pid_str)
                return {"pid": int(pid_str), "process_name": name}
            return None
        # POSIX fallback
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{int(p)}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=3, check=False,
        )
        if result.returncode != 0:
            return None
        pid_text = result.stdout.strip().splitlines()
        if not pid_text:
            return None
        pid = int(pid_text[0])
        name = _ps_name(pid)
        return {"pid": pid, "process_name": name}
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def find_process_on_port(port: int) -> int | None:
    """Find a process PID bound to the given port (best effort, cross platform).

    Prefers psutil for correctness. Exposed for use by launch scripts and tests.
    """
    info = _port_in_use_info("127.0.0.1", port)
    if info and isinstance(info.get("pid"), int):
        return info["pid"]
    return None


def _tasklist_name(pid: str) -> str | None:
    """Process name for a Windows PID via tasklist (best-effort, CSV aware)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        # /NH + CSV: first line is data row. Columns: Image Name, PID, ...
        reader = csv.reader(result.stdout.splitlines())
        row = next(reader, None)
        if row and row[0]:
            return row[0].strip() or None
    except Exception:
        pass
    # Fallback
    line = result.stdout.splitlines()[0].strip()
    return line.strip('"').split('","')[0] or None


def _ps_name(pid: int) -> str | None:
    """Process name for a POSIX PID via /proc/<pid>/comm (no extra deps)."""
    try:
        with open(f"/proc/{int(pid)}/comm", encoding="ascii") as f:
            return f.read().strip() or None
    except (OSError, ValueError):
        return None


# Map llama-server stderr patterns to a single human-readable hint. Returns
# ``None`` when the stderr doesn't match any known failure mode, so the caller
# can fall back to the generic timeout message.
_LAUNCH_ERROR_PATTERNS: tuple[tuple[str, str], ...] = (
    ("couldn't bind HTTP server socket", "Port already in use. Stop the conflicting process or pick a different Port."),
    ("bind: address already in use", "Port already in use. Stop the conflicting process or pick a different Port."),
    ("address already in use", "Port already in use. Stop the conflicting process or pick a different Port."),
    ("cudaMalloc failed", "GPU out of memory. Lower gpu_layers, switch to a smaller quant, or unload other GPU users."),
    ("out of memory", "GPU out of memory. Lower gpu_layers, switch to a smaller quant, or unload other GPU users."),
    ("failed to load model", "Model file not found or unreadable. Check the path in the Parameters panel."),
    ("no such file or directory", "Model file not found or unreadable. Check the path in the Parameters panel."),
    ("unknown model architecture", "Model file is corrupt or unsupported. Re-download the GGUF or check the version of llama-server."),
)


def _classify_launch_error(stderr: str) -> str | None:
    if not stderr:
        return None
    lowered = stderr.lower()
    for needle, hint in _LAUNCH_ERROR_PATTERNS:
        if needle.lower() in lowered:
            return hint
    return None


def list_servers() -> list[dict[str, Any]]:
    refresh_server_states()
    state = read_state()
    servers = []
    for server in state.get("servers", []):
        item = dict(server)
        item["running"] = pid_is_running(item.get("pid"))
        servers.append(item)
    return servers


# A server is considered to have died unexpectedly when its recorded status says
# it should be live (running/starting) but the OS reports the PID is gone. These
# are flagged "crashed" (with the last stderr lines captured) so the dashboard
# can surface the failure and offer restart, instead of silently dropping them.
_LIVE_STATUSES = {"running", "starting", "ready"}

# Threshold above which a freshly-crashed server is annotated as likely-OOM
# based on the recent RAM-pressure rolling window. 0.80 mirrors SwarmUI's
# NetworkBackendUtils pre-crash memory-overload detection heuristic.
_OOM_RAM_THRESHOLD = 0.80
_RAM_HISTORY_MAX = 10  # last ~10 refreshes (~30s at the 3s UI poll cadence)


def _ram_pressure() -> float | None:
    """Current RAM used/total ratio, or None when capacity is unknown."""
    ram = _windows_memory_info() if is_windows() else _posix_memory_info()
    total = ram.get("total_bytes")
    available = ram.get("available_bytes")
    if not total or available is None or total <= 0:
        return None
    used = total - available
    if used < 0:
        return None
    return min(1.0, used / total)


# Rolling window of recent RAM-pressure readings, drained by refresh_server_states
# and inspected when a server transitions to "crashed" to surface a likely-OOM
# annotation. Mirrors SwarmUI's HardwareInfoQueue of recent reports.
_ram_history: deque[float] = deque(maxlen=_RAM_HISTORY_MAX)


def _record_ram_pressure() -> None:
    ratio = _ram_pressure()
    if ratio is not None:
        _ram_history.append(ratio)


def _peak_recent_ram_pressure() -> float:
    """Peak RAM-pressure ratio seen in the rolling window, or 0 when empty."""
    return max(_ram_history) if _ram_history else 0.0


def refresh_server_states() -> None:
    """Detect crashed servers and prune only unsalvageable entries.

    A tracked server whose PID disappeared while its status was still "live" is
    marked ``crashed`` with a snapshot of its last stderr lines and the exit
    time — once, so the dashboard can show it and offer a restart. Entries with
    no PID, or already in a terminal state, are left for ``trim_server_history``
    to age out by count.

    On every refresh the current RAM pressure is appended to a short rolling
    window; a fresh "crashed" transition also receives an ``oom_likely`` flag
    when the window peak exceeded the OOM threshold. This gives the dashboard
    a "your model likely OOM'd" hint without requiring per-process VRAM
    attribution (which the per-server metrics endpoint already covers when the
    server is alive).
    """
    _record_ram_pressure()
    state = read_state()
    servers = state.get("servers", [])
    changed = False
    for server in servers:
        pid = server.get("pid")
        if not pid:
            continue
        if server.get("status") in _LIVE_STATUSES and not pid_is_running(pid):
            server["status"] = "crashed"
            server["running"] = False
            server["crashed_at"] = _now()
            server["last_stderr"] = tail_file(server.get("stderr_log"), lines=40)
            if _peak_recent_ram_pressure() >= _OOM_RAM_THRESHOLD:
                server["oom_likely"] = True
            changed = True
    if changed:
        write_state(state)


def trim_server_history(limit: int = 5) -> None:
    state = read_state()
    servers = state.get("servers", [])
    if len(servers) <= limit:
        return
    # Keep the NEWEST entries. `_upsert_server` appends new servers to the end,
    # so `servers[-limit:]` retains the most recently started ones. Trimming
    # `servers[:limit]` (the oldest) instead silently dropped every freshly
    # launched server once the history filled up, which made the running server
    # invisible to `_find_server` — and made the Stop button a no-op.
    kept = servers[-limit:]
    state["servers"] = kept
    write_state(state)


def purge_server_history(only_non_running: bool = True, all: bool = False) -> dict[str, Any]:
    """Remove tracked server entries.

    - all=True: clear everything.
    - only_non_running=True (default): keep only currently running servers.
    Returns a summary dict for the API.
    """
    state = read_state()
    servers = state.get("servers", [])
    if not servers:
        return {"success": True, "removed": 0, "remaining": 0, "message": "No tracked servers."}

    if all:
        removed = len(servers)
        state["servers"] = []
        write_state(state)
        return {"success": True, "removed": removed, "remaining": 0, "message": f"Removed all {removed} tracked server(s)."}

    if only_non_running:
        kept = [s for s in servers if pid_is_running(s.get("pid"))]
        removed = len(servers) - len(kept)
        state["servers"] = kept
        write_state(state)
        return {"success": True, "removed": removed, "remaining": len(kept), "message": f"Removed {removed} stopped/crashed entry(ies); {len(kept)} kept."}

    # Fallback: no-op keep all
    return {"success": True, "removed": 0, "remaining": len(servers), "message": "Nothing to purge."}


def _find_server(server_id: str | None = None, mode: str | None = None) -> dict[str, Any] | None:
    servers = list_servers()
    if server_id:
        for server in servers:
            if server.get("id") == server_id:
                return server
        return None
    if mode:
        matches = [server for server in servers if server.get("mode") == mode]
        if not matches:
            return None
        # A mode can have several tracked entries (old crashed/timed-out
        # attempts plus the live one). Prefer a running server, and among ties
        # the most recently started, so Stop targets the process that's actually
        # up rather than the first stale corpse in the list.
        running = [server for server in matches if server.get("running")]
        pool = running or matches
        return max(pool, key=lambda server: server.get("started_at") or "")
    return None


def stop_server(server_id: str | None = None, mode: str | None = None, timeout: int = 10) -> dict[str, Any]:
    server = _find_server(server_id, mode)
    if not server:
        return {"success": True, "message": "No tracked server matched the request."}

    raw_pid = server.get("pid")
    if not raw_pid:
        return {"success": True, "message": "Tracked server has no PID to stop."}
    pid = int(raw_pid)
    if not pid_is_running(pid):
        _update_server(server["id"], {"status": "stopped", "running": False, "stopped_at": _now()})
        return {"success": True, "message": f"Tracked PID {pid} is no longer running."}

    if server.get("runtime") == "vllm-wsl":
        return _stop_wsl_vllm(server, timeout)

    if is_windows():
        cmd = ["taskkill", "/PID", str(pid), "/T", "/F"]
    else:
        cmd = ["kill", str(pid)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        still_running = pid_is_running(pid)
        _update_server(
            server["id"],
            {
                "status": "stop_failed",
                "running": still_running,
                "stopped_at": _now(),
                "stop_stdout": "",
                "stop_stderr": str(exc),
            },
        )
        return {
            "success": False,
            "message": str(exc),
            "server": _find_server(server["id"]),
        }

    if result.returncode != 0:
        still_running = pid_is_running(pid)
        _update_server(
            server["id"],
            {
                "status": "stop_failed",
                "running": still_running,
                "stopped_at": _now(),
                "stop_stdout": result.stdout.strip(),
                "stop_stderr": result.stderr.strip(),
            },
        )
        return {
            "success": False,
            "message": result.stdout.strip() or result.stderr.strip() or f"taskkill returned {result.returncode} for PID {pid}.",
            "server": _find_server(server["id"]),
        }

    def _stopped_ok(message: str) -> dict[str, Any]:
        _update_server(
            server["id"],
            {
                "status": "stopped",
                "running": False,
                "stopped_at": _now(),
                "stop_stdout": result.stdout.strip(),
                "stop_stderr": result.stderr.strip(),
            },
        )
        return {"success": True, "message": message, "server": _find_server(server["id"])}

    if _wait_gone(pid, 5):
        return _stopped_ok(result.stdout.strip() or result.stderr.strip() or f"Stopped PID {pid}.")

    # SIGTERM was ignored. Windows taskkill already forced (/F); on POSIX
    # escalate to SIGKILL so the Stop button can't be defeated by a hung server.
    if not is_windows():
        subprocess.run(["kill", "-9", str(pid)], capture_output=True, text=True, timeout=timeout, check=False)
        if _wait_gone(pid, 3):
            return _stopped_ok(f"Stopped PID {pid} with SIGKILL after it ignored SIGTERM.")

    _update_server(
        server["id"],
        {
            "status": "stop_failed",
            "running": True,
            "stopped_at": _now(),
            "stop_stdout": result.stdout.strip(),
            "stop_stderr": result.stderr.strip(),
        },
    )
    return {
        "success": False,
        "message": f"PID {pid} did not exit after SIGTERM and SIGKILL.",
        "server": _find_server(server["id"]),
    }


WSL_STOP_NO_ROOT_MARKER = "LCC_WSL_STOP_NO_ROOT"


def _wsl_stop_script(pidfile: str) -> str:
    """Build the in-distro Python that kills the vLLM tree rooted at the pidfile.

    Pass Python directly through wsl.exe. A `bash -lc` script containing
    `$p`/`$(...)` is expanded once by WSL's command bridge before the target
    bash sees it, which breaks on Windows and can leave EngineCore children.
    """

    return f"""
import os
import signal
import sys
import time

pidfile = {pidfile!r}
try:
    root = int(open(pidfile).read().strip())
except (OSError, ValueError):
    root = 0
# A missing/garbage pidfile (WSL restarted, /tmp cleared) must abort here. The
# descendant walk below would start from PID 0, and on Linux PID 1 has ppid 0,
# so it would collect and then SIGKILL every process in the distro.
if root <= 0:
    print({WSL_STOP_NO_ROOT_MARKER!r})
    sys.exit(3)
parents = {{}}
for entry in os.listdir('/proc'):
    if not entry.isdigit():
        continue
    try:
        parents[int(entry)] = int(open(f'/proc/{{entry}}/stat').read().split()[3])
    except (FileNotFoundError, ProcessLookupError, ValueError):
        pass
descendants = []
front = [root]
for parent in front:
    for child, ppid in parents.items():
        if ppid == parent and child not in descendants:
            descendants.append(child)
            front.append(child)
targets = list(reversed(descendants)) + [root]
for sig in (signal.SIGTERM, signal.SIGKILL):
    for target in targets:
        try:
            os.kill(target, sig)
        except (ProcessLookupError, PermissionError):
            pass
    time.sleep(1)
if os.path.exists(pidfile):
    os.remove(pidfile)
"""


def _stop_wsl_vllm(server: dict[str, Any], timeout: int) -> dict[str, Any]:
    """Stop the Linux vLLM process tree, then ensure its WSL client exits."""

    pid = int(server["pid"])
    distro = str(server.get("wsl_distro") or "Ubuntu-24.04")
    pidfile = str(server.get("wsl_pidfile") or "")
    wsl = str(server.get("wsl_binary") or shutil.which("wsl.exe") or "wsl.exe")
    if not pidfile:
        return {"success": False, "message": "Tracked vLLM server has no WSL pidfile.", "server": server}
    stop_script = _wsl_stop_script(pidfile)
    try:
        result = subprocess.run(
            [wsl, "-d", distro, "--", "python3", "-c", stop_script],
            capture_output=True,
            text=True,
            timeout=max(timeout, 15),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result = subprocess.CompletedProcess([], 1, "", str(exc))

    if WSL_STOP_NO_ROOT_MARKER in (result.stdout or ""):
        # The tree was never identified, so nothing was killed. Reporting success
        # here (after only reaping the wsl.exe client) would strand vLLM holding
        # VRAM with no tracked PID left to stop it.
        _update_server(
            server["id"],
            {
                "status": "stop_failed",
                "running": True,
                "stopped_at": _now(),
                "stop_stdout": (result.stdout or "").strip(),
                "stop_stderr": (result.stderr or "").strip(),
            },
        )
        return {
            "success": False,
            "message": (
                f"WSL vLLM stop aborted: pidfile {pidfile} is missing or unreadable in distro {distro}, "
                "so the Linux process tree could not be identified. Stop vLLM inside WSL manually."
            ),
            "server": _find_server(server["id"]),
        }

    if not _wait_gone(pid, 5) and is_windows():
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=timeout, check=False)
    stopped = not pid_is_running(pid)
    patch = {
        "status": "stopped" if stopped else "stop_failed",
        "running": not stopped,
        "stopped_at": _now(),
        "stop_stdout": (result.stdout or "").strip(),
        "stop_stderr": (result.stderr or "").strip(),
    }
    _update_server(server["id"], patch)
    return {
        "success": stopped,
        "message": "Stopped WSL vLLM server." if stopped else "WSL vLLM process did not exit.",
        "server": _find_server(server["id"]),
    }


def _update_server(server_id: str, patch: dict[str, Any]) -> None:
    state = read_state()
    servers = state.setdefault("servers", [])
    for idx, server in enumerate(servers):
        if server.get("id") == server_id:
            servers[idx] = {**server, **patch}
            write_state(state)
            return


def _upsert_server(server: dict[str, Any]) -> None:
    state = read_state()
    servers = state.setdefault("servers", [])
    for idx, existing in enumerate(servers):
        if existing.get("id") == server.get("id"):
            servers[idx] = server
            write_state(state)
            return
    servers.append(server)
    write_state(state)


def _health_url(host: str, port: int) -> str:
    probe_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    return f"http://{probe_host}:{int(port)}/v1/models"


def wait_until_ready(host: str, port: int, pid: int, timeout_seconds: int = 45) -> bool:
    deadline = time.time() + timeout_seconds
    url = _health_url(host, port)
    while time.time() < deadline:
        if not pid_is_running(pid):
            return False
        try:
            with urllib.request.urlopen(url, timeout=1):
                return True
        except Exception:
            time.sleep(1)
    return False


def _profile_by_mode(mode: str, project_root: str | Path | None, model_dirs: list[str | Path] | None) -> ResolvedProfile | None:
    for profile in resolve_profiles(project_root=project_root, model_dirs=model_dirs):
        if profile.mode == mode:
            return profile
    return None


def prepare_launch_command(
    mode: str,
    project_root: str | Path | None = None,
    model_dirs: list[str | Path] | None = None,
    overrides: dict[str, Any] | None = None,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve() if project_root else find_project_root()
    app_config = config or AppConfig.load()
    try:
        resolved = _profile_by_mode(mode, root, model_dirs or app_config.model_dirs)
    except ManifestReadError as exc:
        return {"success": False, "error": f"Manifest read error: {exc}"}
    if not resolved:
        return {"success": False, "error": f"Unknown profile mode: {mode}"}
    if not resolved.launchable or not resolved.model:
        return {
            "success": False,
            "error": "Profile is not launchable.",
            "profile": resolved.to_dict(),
        }

    params = dict(resolved.params)
    params.update(overrides or {})
    params.setdefault("host", app_config.default_host)
    params.setdefault("port", app_config.default_port)

    runtime = str(params.get("runtime") or "llama.cpp").strip() or "llama.cpp"
    if runtime == "vllm-wsl":
        env = detect_runtime(runtime, root, config=app_config)
        if env is None:
            return {"success": False, "error": f"Unknown runtime: {runtime}"}
        if not env.available or not env.binary_path:
            return {"success": False, "error": "vLLM is not installed in the configured WSL environment.", "environment": env.to_dict()}
        pidfile = f"/tmp/lcc-vllm/{mode}.pid"
        command = build_wsl_vllm_args(
            env.binary_path,
            str(env.details.get("distro") or app_config.wsl_distro),
            str(env.details.get("venv") or app_config.vllm_wsl_venv),
            resolved.model["path"],
            params,
            pidfile,
        )
        return {
            "success": True,
            "environment": env.to_dict(),
            "profile": resolved.to_dict(),
            "command": command.to_dict(),
            "params": params,
            "warnings": resolved.warnings + command.warnings,
            "runtime_metadata": {
                "wsl_binary": env.details.get("wsl_binary") or env.binary_path,
                "wsl_distro": env.details.get("distro") or app_config.wsl_distro,
                "wsl_pidfile": pidfile,
            },
        }
    if runtime != "llama.cpp":
        env = detect_runtime(runtime, root, config=app_config)
        if env is None:
            return {"success": False, "error": f"Unknown runtime: {runtime}"}
        return {"success": False, "error": f"{env.name} is detected but its launcher is not implemented.", "environment": env.to_dict()}

    llama = detect_llama_cpp(root, config=app_config)
    if not llama.binary_path:
        return {"success": False, "error": "llama-server was not found.", "environment": llama.to_dict()}

    command = build_llama_server_args(
        llama.binary_path,
        resolved.model["path"],
        params,
        extra_args=app_config.extra_llama_args,
    )
    warnings = resolved.warnings + command.warnings
    return {
        "success": True,
        "profile": resolved.to_dict(),
        "environment": llama.to_dict(),
        "command": command.to_dict(),
        "params": params,
        "warnings": warnings,
    }


def start_profile(
    mode: str,
    project_root: str | Path | None = None,
    model_dirs: list[str | Path] | None = None,
    overrides: dict[str, Any] | None = None,
    stop_existing: bool = False,
    wait_ready: bool = True,
    ready_timeout_seconds: int = 45,
) -> dict[str, Any]:
    prepared = prepare_launch_command(mode, project_root, model_dirs, overrides)
    if not prepared.get("success"):
        return prepared

    existing = _find_server(mode=mode)
    if existing and existing.get("running"):
        if not stop_existing:
            return {
                "success": False,
                "error": f"Profile '{mode}' already has a tracked running server.",
                "server": existing,
            }
        stop_result = stop_server(mode=mode)
        if not stop_result.get("success"):
            return {"success": False, "error": "Could not stop existing tracked server.", "stop_result": stop_result}

    command = LaunchCommand(
        argv=prepared["command"]["argv"],
        cwd=prepared["command"]["cwd"],
        warnings=prepared["command"].get("warnings", []),
    )
    # Pre-flight: refuse to spawn a process that will fail immediately on a
    # bound port. The old code launched llama-server, waited 45 s for it to
    # become ready, and only surfaced the error after the user had stared
    # at the "starting…" spinner for the full timeout. Checking first turns
    # the bind-fail into a single immediate error with an actionable hint.
    #
    # There are two distinct bind-fail modes that get *different* error
    # copy:
    #
    #   - ``reserved``: the port is inside Windows' reserved dynamic range
    #     (e.g. 8080/8081 with the default netsh config). The bind fails
    #     with EACCES, nothing is listening on the port, and the right
    #     action is "pick a port outside the range" rather than "kill the
    #     holder". This is the failure mode that the Qwen-AgentWorld
    #     profile was hitting.
    #   - ``in_use``: a real listener is on the port (or we don't know who).
    #     Get the holder via ``_port_in_use_info`` so the UI can show a
    #     process name.
    host = str(prepared["params"].get("host", "127.0.0.1"))
    port = int(prepared["params"].get("port", 8080))
    probe = _probe_port(host, port)
    if not probe["free"]:
        reason = probe.get("reason", "in_use")
        info = None
        process_part = ""
        if reason == "in_use":
            info = _port_in_use_info(host, port) or {}
            if info.get("process_name") and info.get("pid"):
                process_part = f" by {info['process_name']} (PID {info['pid']})"
            elif info.get("process_name"):
                process_part = f" by {info['process_name']}"
            elif info.get("pid"):
                process_part = f" by PID {info['pid']}"
        # Suggest the next port above the reserved range when the issue is
        # reservation; otherwise just port + 1 (which may itself be free,
        # or may itself be reserved — the function handles the bump).
        if reason == "reserved":
            rng = probe.get("range") or {}
            rng_start = rng.get("start", "?")
            rng_end = rng.get("end", "?")
            suggested = _next_free_port(host, port)
            message = (
                f"Port {port} is in a Windows-reserved range "
                f"({rng_start}-{rng_end}); the OS denies bind. "
                f"Pick a Port value above {rng_end} and try again."
            )
        else:
            suggested = _next_free_port(host, port + 1)
            message = (
                f"Port {port} is already bound{process_part}. "
                f"Stop the conflicting process, or change the Port parameter and try again."
            )
        return {
            "success": False,
            "error": message,
            "port_in_use": True,
            "port_in_use_reason": reason,
            "port": port,
            "port_holder": info,
            "reserved_range": probe.get("range"),
            "suggested_port": suggested,
            "prepared": prepared,
        }
    mode_slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in mode).strip("-") or "server"
    stdout_path = log_dir() / f"{mode_slug}-stdout.log"
    stderr_path = log_dir() / f"{mode_slug}-stderr.log"
    stdout_handle = stdout_path.open("w", encoding="utf-8", errors="replace")
    stderr_handle = stderr_path.open("w", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            command.argv,
            cwd=command.cwd,
            stdout=stdout_handle,
            stderr=stderr_handle,
            stdin=subprocess.DEVNULL,
            shell=False,
            # Detach so the managed server outlives the control center: a
            # terminal/process-group signal (Ctrl-C, systemd stop) to us must
            # not take down the servers we track in state. setsid on POSIX,
            # ignored on Windows (CREATE_NO_WINDOW already detaches the console).
            start_new_session=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        stdout_handle.close()
        stderr_handle.close()
        return {"success": False, "error": str(exc), "prepared": prepared}
    finally:
        stdout_handle.close()
        stderr_handle.close()

    params = prepared["params"]
    server_id = f"{mode}-{proc.pid}"
    server = {
        "id": server_id,
        "mode": mode,
        "pid": proc.pid,
        "status": "starting",
        "running": True,
        "host": host,
        "port": port,
        "model_path": prepared["profile"]["model"]["path"] if prepared["profile"].get("model") else None,
        "model_alias": str(params.get("alias") or mode),
        "reasoning": bool(params.get("reasoning", False)),
        "command_line": command.command_line,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "started_at": _now(),
        "warnings": prepared.get("warnings", []),
        "runtime": str(prepared["params"].get("runtime") or "llama.cpp"),
    }
    server.update(prepared.get("runtime_metadata") or {})
    _upsert_server(server)
    app_config = AppConfig.load()
    trim_server_history(app_config.server_history_limit)

    if wait_ready:
        profile_timeout = int(prepared["params"].get("ready_timeout_seconds") or 0)
        effective_timeout = max(ready_timeout_seconds, profile_timeout)
        ready = wait_until_ready(server["host"], server["port"], proc.pid, effective_timeout)
        _update_server(
            server_id,
            {
                "status": "running" if ready else "startup_timeout",
                "running": pid_is_running(proc.pid),
                "ready_at": _now() if ready else None,
            },
        )
        if not ready:
            stderr_text = tail_file(stderr_path)
            # Map common llama-server startup failures to a short hint the
            # dashboard can surface alongside the (still long) raw stderr.
            hint = _classify_launch_error(stderr_text)
            message = "Server process started but did not become ready before timeout."
            if hint:
                message = f"{message} {hint}"
            return {
                "success": False,
                "error": message,
                "hint": hint,
                "server": _find_server(server_id),
                "stderr_tail": stderr_text,
            }

    return {"success": True, "server": _find_server(server_id), "prepared": prepared}


def server_logs(server_id: str, lines: int = 200) -> dict[str, Any]:
    server = _find_server(server_id)
    if not server:
        return {"success": False, "error": f"Unknown tracked server: {server_id}"}
    return {
        "success": True,
        "server": server,
        "stdout": tail_file(server.get("stdout_log"), lines),
        "stderr": tail_file(server.get("stderr_log"), lines),
    }
