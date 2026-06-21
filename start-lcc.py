from __future__ import annotations

import argparse
import os
import signal
import sys
import time
import subprocess
from pathlib import Path

APP_NAME = "llama-control-center"
PID_FILENAME = "lcc-api.pid"
STDOUT_LOG = "lcc-api-out.log"
STDERR_LOG = "lcc-api-err.log"


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


def find_process_on_port(port: int) -> int | None:
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                check=True,
            )
            for line in result.stdout.splitlines():
                parts = line.strip().split()
                for part in parts:
                    if part == f":{port}":
                        idx = parts.index(part) + 1
                        if idx < len(parts):
                            return int(parts[idx])
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


def stop_server(pid: int | None = None) -> int:
    if pid is None:
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
        port = 8716
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

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=stdout_f,
            stderr=stderr_f,
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
    start_parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    start_parser.add_argument("--port", type=int, default=8716, help="Bind port")
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
            print(f"  Dashboard: http://{pid}")
            return 0
        else:
            print("Server is not running.")
            return 1
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
