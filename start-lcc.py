from __future__ import annotations

import argparse
import os
import signal
import sys
import time
import subprocess
from pathlib import Path

# Prefer the hardened, centralized implementations from the core package.
# Fall back to the local definitions (for very early bootstrap or unusual installs).
try:
    from lcc_core.server_manager import pid_is_running as _core_pid_is_running
    from lcc_core.server_manager import find_process_on_port as _core_find_process_on_port
except Exception as _core_exc:
    # Surface this loudly: a broken lcc_core (e.g. a half-resolved merge or bad
    # edit) otherwise hides behind the fallbacks and produces misleading
    # messages like "port in use by <your browser's PID>".
    print(f"Warning: could not import lcc_core ({_core_exc}); using local fallbacks.", file=sys.stderr)
    _core_pid_is_running = None  # type: ignore
    _core_find_process_on_port = None  # type: ignore

APP_NAME = "llama-control-center"
PID_FILENAME = "lcc-api.pid"
STDOUT_LOG = "lcc-api-out.log"
STDERR_LOG = "lcc-api-err.log"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8716


def get_pid_file_path() -> Path:
    return Path.cwd() / PID_FILENAME


def get_pid() -> int | None:
    pid_file = get_pid_file_path()
    if not pid_file.is_file():
        return None
    try:
        return int(pid_file.read_text().strip())
    except (OSError, ValueError):
        return None


def pid_is_running(pid: int) -> bool:
    if _core_pid_is_running is not None:
        try:
            return bool(_core_pid_is_running(pid))
        except Exception:
            pass
    # Local fallback (should rarely be reached)
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=True,
            )
            return True
        except subprocess.CalledProcessError:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def write_pid(pid: int) -> None:
    get_pid_file_path().write_text(str(pid))


def remove_pid() -> None:
    pid_file = get_pid_file_path()
    if pid_file.is_file():
        pid_file.unlink()


def _parse_netstat_for_port(output: str, port: int) -> int | None:
    """Return the PID LISTENING on ``port`` from ``netstat -ano`` output.

    Only LISTENING lines whose *local* address ends in ``:{port}`` count.
    Client-side connections that merely mention the port as a foreign
    address (a browser talking to the dashboard) must never match.
    """
    target = f":{port}"
    for line in output.splitlines():
        parts = line.split()
        # Typical: Proto LocalAddr ForeignAddr State PID
        if len(parts) < 5:
            continue
        proto, local_addr, _foreign, state, pid = parts[0], parts[1], parts[2], parts[3], parts[-1]
        if not proto.upper().startswith("TCP"):
            continue
        if state.upper() != "LISTENING":
            continue
        if not local_addr.endswith(target):
            continue
        if pid.isdigit():
            return int(pid)
    return None


def find_process_on_port(port: int) -> int | None:
    if _core_find_process_on_port is not None:
        try:
            return _core_find_process_on_port(port)
        except Exception:
            pass
    # Local fallback with slightly hardened parsing (still best-effort)
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                check=True,
            )
            return _parse_netstat_for_port(result.stdout, port)
        except (subprocess.CalledProcessError, ValueError, IndexError):
            pass
    else:
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                check=True,
            )
            pids = result.stdout.strip().splitlines()
            if pids:
                return int(pids[0])
        except (subprocess.CalledProcessError, ValueError):
            pass
    return None


def stop_model_servers() -> int:
    """Reap the llama-server processes the dashboard spawned.

    Spawned servers are detached (`start_new_session`) so they outlive the API
    daemon — stopping the daemon alone orphans them, leaving the model resident
    and the port bound. Reuse the server manager's SIGTERM->SIGKILL teardown
    over every tracked server, the same path the dashboard's Stop button uses.
    Best-effort: a missing/broken server manager never blocks the daemon stop.
    """
    try:
        from lcc_core import server_manager
    except Exception as exc:
        print(f"Could not load server manager to stop model servers: {exc}", file=sys.stderr)
        return 0
    try:
        servers = server_manager.list_servers()
    except Exception as exc:
        print(f"Could not list tracked model servers: {exc}", file=sys.stderr)
        return 0

    stopped = 0
    for server in servers:
        if not server.get("running") or not server.get("pid"):
            continue
        label = server.get("mode") or server.get("id") or "server"
        server_pid = server.get("pid")
        try:
            result = server_manager.stop_server(server_id=server.get("id"))
        except Exception as exc:
            print(f"Error stopping model server '{label}' (PID {server_pid}): {exc}", file=sys.stderr)
            continue
        if result.get("success"):
            stopped += 1
            print(f"Stopped model server '{label}' (PID {server_pid}).")
        else:
            print(
                f"Could not stop model server '{label}' (PID {server_pid}): "
                f"{result.get('message', 'unknown error')}",
                file=sys.stderr,
            )
    return stopped


def stop_server(pid: int | None = None) -> int:
    if pid is None:
        # Reap spawned llama-server children before tearing down the daemon, so
        # `stop` cleans them up even when the daemon PID file is already gone.
        stop_model_servers()
        pid = get_pid()
    if pid is not None and pid_is_running(pid):
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                )
            else:
                os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                time.sleep(0.25)
                if not pid_is_running(pid):
                    print(f"Server (PID {pid}) stopped.")
                    remove_pid()
                    return 0
            if pid_is_running(pid):
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        capture_output=True,
                        text=True,
                    )
                else:
                    os.kill(pid, signal.SIGKILL)
                print(f"Server (PID {pid}) force-killed.")
                remove_pid()
                return 0
        except Exception as exc:
            print(f"Error stopping server: {exc}", file=sys.stderr)
            return 1
    else:
        port = DEFAULT_PORT
        fallback_pid = find_process_on_port(port)
        if fallback_pid is not None:
            print(f"No PID file found, but found process {fallback_pid} on port {port}.")
            confirm = input(f"Stop process {fallback_pid}? [y/N]: ").strip().lower()
            if confirm in ("y", "yes"):
                return stop_server(fallback_pid)
        print("Server is not running.")
        remove_pid()
        return 0


def start_server(host: str, port: int, reload: bool) -> int:
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        print("Install dependencies first: pip install -r requirements.txt", file=sys.stderr)
        return 1

    existing_pid = get_pid()
    if existing_pid is not None and pid_is_running(existing_pid):
        print(f"Server is already running (PID {existing_pid}).")
        print("Run 'python stop-lcc.py' to stop it first.")
        return 1

    fallback_pid = find_process_on_port(port)
    if fallback_pid is not None:
        print(f"Port {port} is already in use by process {fallback_pid}.")
        print("Run 'python stop-lcc.py' to stop it first.")
        return 1

    stdout_path = Path.cwd() / STDOUT_LOG
    stderr_path = Path.cwd() / STDERR_LOG

    with stdout_path.open("a") as stdout_f, stderr_path.open("a") as stderr_f:
        cmd = [
            sys.executable,
            "-m",
            "lcc_api",
            "--host",
            host,
            "--port",
            str(port),
        ]
        if reload:
            cmd.append("--reload")

        # Detach so the daemon outlives the launching terminal: a console control
        # event (Ctrl-C, closing the PowerShell window) otherwise hits the whole
        # process group and kills the API, leaving a stale pid file behind.
        # New process group + no console on Windows, setsid on POSIX.
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
                subprocess, "CREATE_NO_WINDOW", 0
            )

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=stdout_f,
            stderr=stderr_f,
            start_new_session=True,
            creationflags=creationflags,
        )

        if sys.platform == "win32":
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass

        time.sleep(1)
        if proc.poll() is not None:
            print(f"Server failed to start. Check {stderr_path} for details.", file=sys.stderr)
            return 1

        write_pid(proc.pid)
        print(f"Server started (PID {proc.pid}).")
        print(f"  Dashboard: http://{host}:{port}/")
        print(f"  API docs:  http://{host}:{port}/docs")
        print(f"  Logs:      {stdout_path}")
        print(f"Run 'python stop-lcc.py' to stop the server.")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Start or stop the Llama Control Center server.",
    )
    subparsers = parser.add_subparsers(dest="command")

    start_parser = subparsers.add_parser("start", help="Start the server")
    start_parser.add_argument("--host", default=DEFAULT_HOST, help="Bind address")
    start_parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port")
    start_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    subparsers.add_parser("stop", help="Stop the running server")
    subparsers.add_parser("status", help="Show server status")

    args = parser.parse_args(argv)

    if args.command == "start":
        return start_server(args.host, args.port, args.reload)
    elif args.command == "stop":
        return stop_server()
    elif args.command == "status":
        pid = get_pid()
        if pid is not None and pid_is_running(pid):
            print(f"Server is running (PID {pid}).")
            print(f"  Dashboard: http://{DEFAULT_HOST}:{DEFAULT_PORT}/")
            return 0
        else:
            print("Server is not running.")
            return 1
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
