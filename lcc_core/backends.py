from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import importlib.util
import shlex
from pathlib import Path
from urllib.parse import urlparse

from .config import AppConfig
from .paths import candidate_llama_roots, executable_names, is_windows
from .schema import Environment


DEFAULT_TIMEOUT_SECONDS = 0.8


def _request_json(url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> tuple[bool, dict | list | None, str | None]:
    req = urllib.request.Request(url, headers={"User-Agent": "llama-control-center/portable-core"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        return True, json.loads(raw.decode("utf-8")), None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return False, None, str(exc)


def _normalize_base_url(raw: str | None, default: str) -> str:
    value = (raw or default).strip()
    if "://" not in value:
        value = f"http://{value}"
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if host in {"0.0.0.0", "::"}:
        replacement = "127.0.0.1"
        netloc = replacement
        if parsed.port:
            netloc = f"{replacement}:{parsed.port}"
        value = parsed._replace(netloc=netloc).geturl()
    return value.rstrip("/")


def _find_executable(base_name: str, env_vars: list[str] | None = None, roots: list[Path] | None = None) -> str | None:
    for env_var in env_vars or []:
        override = os.environ.get(env_var)
        if override and Path(override).expanduser().is_file():
            return str(Path(override).expanduser())

    for root in roots or []:
        for name in executable_names(base_name):
            for subdir in [Path("."), Path("bin"), Path("build") / "bin"]:
                candidate = root / subdir / name
                if candidate.is_file():
                    return str(candidate)

    for name in executable_names(base_name):
        found = shutil.which(name)
        if found:
            return found
    return None


def _configured_file(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value).expanduser()
    return str(path) if path.is_file() else None


def _configured_roots(config: AppConfig) -> list[Path]:
    roots: list[Path] = []
    for raw in config.runtime_dirs:
        if raw:
            roots.append(Path(raw).expanduser())
    for raw in [config.llama_server_path, config.llama_fit_params_path]:
        if raw:
            path = Path(raw).expanduser()
            roots.append(path.parent if path.suffix else path)
    return [path for path in roots if path.is_dir()]


# `llama-server --version` prints `version: b4488 (build c8a8a9d5)`. Keeping the
# whole line makes the stored version unparseable (and the build hash can be
# mistaken for a version), so pull out just the token after `version:`.
_VERSION_TOKEN_RE = re.compile(r"version:\s*(\S+)", re.IGNORECASE)


def _binary_version(binary_path: str | None, timeout: float = 2.0) -> str | None:
    if not binary_path:
        return None
    try:
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr).strip()
    if not output:
        return None
    for line in output.splitlines():
        if "version:" in line.lower():
            match = _VERSION_TOKEN_RE.search(line)
            return (match.group(1) if match else line)[:240]
    return output.splitlines()[0][:240]


def detect_llama_cpp(project_root: Path | None = None, config: AppConfig | None = None) -> Environment:
    app_config = config or AppConfig.load()
    roots = _configured_roots(app_config) + candidate_llama_roots(project_root)
    server = _configured_file(app_config.llama_server_path) or _find_executable(
        "llama-server", ["LLAMA_SERVER", "LLAMA_SERVER_BIN"], roots
    )
    cli = _find_executable("llama-cli", ["LLAMA_CLI", "LLAMA_CLI_BIN"], roots)
    fit = _configured_file(app_config.llama_fit_params_path) or _find_executable(
        "llama-fit-params", ["LLAMA_FIT_PARAMS", "LLAMA_FIT_PARAMS_BIN"], roots
    )

    configured_url = os.environ.get("LLAMA_SERVER_URL")
    if configured_url:
        api_url = _normalize_base_url(configured_url, configured_url)
    else:
        port = os.environ.get("LLAMA_SERVER_PORT") or str(app_config.default_port or 8080)
        host = os.environ.get("LLAMA_SERVER_HOST") or app_config.default_host or "127.0.0.1"
        api_url = _normalize_base_url(f"{host}:{port}", "http://127.0.0.1:8080")

    ok, models_payload, error = _request_json(f"{api_url}/v1/models")
    model_count = None
    if ok and isinstance(models_payload, dict):
        model_count = len(models_payload.get("data", []) or [])

    warnings: list[str] = []
    if not server:
        warnings.append("llama-server was not found on PATH, LLAMA_SERVER, or discovered project roots.")

    return Environment(
        id="llama.cpp",
        kind="local_binary",
        name="llama.cpp",
        available=bool(server or ok),
        binary_path=server,
        api_url=api_url if ok else None,
        version=_binary_version(server),
        model_count=model_count,
        details={
            "llama_cli": cli,
            "llama_fit_params": fit,
            "probe_url": api_url,
            "probe_error": None if ok else error,
            "candidate_roots": [str(path) for path in roots],
        },
        warnings=warnings,
    )


def detect_ollama() -> Environment:
    api_url = _normalize_base_url(os.environ.get("OLLAMA_HOST"), "http://127.0.0.1:11434")
    ok, payload, error = _request_json(f"{api_url}/api/tags")
    model_count = None
    if ok and isinstance(payload, dict):
        model_count = len(payload.get("models", []) or [])
    binary = _find_executable("ollama", ["OLLAMA_BIN"])
    version = _binary_version(binary) if binary else None
    return Environment(
        id="ollama",
        kind="api_runtime",
        name="Ollama",
        available=ok,
        binary_path=binary,
        api_url=api_url if ok else None,
        version=version,
        model_count=model_count,
        details={"probe_url": api_url, "probe_error": None if ok else error},
    )


def detect_lm_studio() -> Environment:
    api_url = _normalize_base_url(os.environ.get("LMSTUDIO_HOST"), "http://127.0.0.1:1234")
    ok, payload, error = _request_json(f"{api_url}/v1/models")
    model_count = None
    if ok and isinstance(payload, dict):
        model_count = len(payload.get("data", []) or [])
    return Environment(
        id="lm-studio",
        kind="api_runtime",
        name="LM Studio",
        available=ok,
        api_url=api_url if ok else None,
        model_count=model_count,
        details={"probe_url": api_url, "probe_error": None if ok else error},
    )


def detect_vllm() -> Environment:
    api_url = _normalize_base_url(os.environ.get("VLLM_HOST"), "http://127.0.0.1:8000")
    ok, payload, error = _request_json(f"{api_url}/v1/models")
    model_count = None
    if ok and isinstance(payload, dict):
        model_count = len(payload.get("data", []) or [])
    binary = _find_executable("vllm", ["VLLM_BIN"])
    return Environment(
        id="vllm",
        kind="api_or_binary_runtime",
        name="vLLM",
        available=bool(ok or binary),
        binary_path=binary,
        api_url=api_url if ok else None,
        model_count=model_count,
        details={"probe_url": api_url, "probe_error": None if ok else error},
    )


def detect_wsl_vllm(config: AppConfig | None = None) -> Environment:
    app_config = config or AppConfig.load()
    if not is_windows():
        return Environment(
            id="vllm-wsl",
            kind="wsl_runtime",
            name="vLLM (WSL2)",
            available=False,
            details={"reason": "The WSL launcher is only available on Windows."},
        )
    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        return Environment(
            id="vllm-wsl",
            kind="wsl_runtime",
            name="vLLM (WSL2)",
            available=False,
            warnings=["wsl.exe was not found on PATH."],
        )

    distro = app_config.wsl_distro or "Ubuntu-24.04"
    venv = app_config.vllm_wsl_venv or "/opt/lcc-vllm"
    executable = f"{venv.rstrip('/')}/bin/vllm"
    python = f"{venv.rstrip('/')}/bin/python"
    # `vllm --version` imports the full multimodal stack and can take tens of
    # seconds on a cold WSL process. Package metadata is instant and is enough
    # to prove this managed environment is installed.
    version_code = (
        "import importlib.metadata,importlib.util,json,os,shutil; "
        "print(json.dumps({'version':importlib.metadata.version('vllm'),"
        "'cc':bool(shutil.which('cc')),'ninja':bool(shutil.which('ninja')),"
        "'nvcc':os.access('/usr/local/cuda/bin/nvcc',os.X_OK),"
        "'flashinfer_jit_cache':bool(importlib.util.find_spec('flashinfer_jit_cache'))}))"
    )
    linux_path = "/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
    probe = (
        f"export PATH={shlex.quote(linux_path)}; "
        f"test -x {shlex.quote(executable)} && {shlex.quote(python)} -c {shlex.quote(version_code)}"
    )
    version = None
    prerequisites: dict[str, bool] = {}
    error = None
    try:
        result = subprocess.run(
            [wsl, "-d", distro, "--", "bash", "-lc", probe],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        if result.returncode == 0:
            payload = json.loads((result.stdout or result.stderr).strip().splitlines()[0])
            version = str(payload.pop("version", ""))[:240] or None
            prerequisites = {str(key): bool(value) for key, value in payload.items()}
        else:
            error = (result.stderr or result.stdout).strip() or f"probe exited {result.returncode}"
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError) as exc:
        error = str(exc)

    api_url = _normalize_base_url(os.environ.get("VLLM_WSL_HOST"), "http://127.0.0.1:18027")
    ok, payload, api_error = _request_json(f"{api_url}/v1/models")
    model_count = len(payload.get("data", []) or []) if ok and isinstance(payload, dict) else None
    missing = [name for name, present in prerequisites.items() if not present]
    available = bool((version and not missing) or ok)
    warnings: list[str] = []
    if not version and not ok:
        warnings.append(f"vLLM was not found at {executable} in WSL distro {distro}.")
    if missing:
        warnings.append(f"vLLM WSL build prerequisites are missing: {', '.join(missing)}.")
    return Environment(
        id="vllm-wsl",
        kind="wsl_runtime",
        name="vLLM (WSL2)",
        available=available,
        binary_path=wsl if available else None,
        api_url=api_url if ok else None,
        version=version,
        model_count=model_count,
        details={
            "wsl_binary": wsl,
            "distro": distro,
            "venv": venv,
            "vllm_executable": executable,
            "prerequisites": prerequisites,
            "missing_prerequisites": missing,
            "probe_error": error,
            "api_probe_error": None if ok else api_error,
            "launchable": available,
        },
        warnings=warnings,
    )


def detect_mlx() -> Environment:
    module_available = importlib.util.find_spec("mlx_lm") is not None
    is_macos = os.uname().sysname == "Darwin" if hasattr(os, "uname") else False
    server_binary = _find_executable("mlx_lm.server", ["MLX_LM_SERVER", "MLX_SERVER_BIN"])
    warnings: list[str] = []
    if not is_macos:
        warnings.append("MLX is intended for macOS with Apple Silicon.")
    if is_macos and not module_available and not server_binary:
        warnings.append("MLX was not found. Install mlx-lm in the Python environment to enable it.")
    return Environment(
        id="mlx",
        kind="local_runtime",
        name="MLX",
        available=bool(is_macos and (module_available or server_binary)),
        binary_path=server_binary,
        details={
            "python_module": "mlx_lm" if module_available else None,
            "acceleration_backend": "metal",
            "platform_supported": is_macos,
        },
        warnings=warnings,
    )


def detect_wsl_llama_cpp() -> Environment:
    if not is_windows():
        return Environment(
            id="wsl-llama.cpp",
            kind="wsl_runtime",
            name="WSL llama.cpp",
            available=False,
            details={"reason": "WSL detection is only relevant on Windows."},
        )

    wsl = shutil.which("wsl.exe") or shutil.which("wsl")
    if not wsl:
        return Environment(
            id="wsl-llama.cpp",
            kind="wsl_runtime",
            name="WSL llama.cpp",
            available=False,
            warnings=["wsl.exe was not found on PATH."],
        )

    probe = "command -v llama-server || command -v llama.cpp/build/bin/llama-server || true"
    try:
        result = subprocess.run(
            [wsl, "sh", "-lc", probe],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        binary = result.stdout.strip().splitlines()[0] if result.stdout.strip() else None
    except (OSError, subprocess.SubprocessError) as exc:
        return Environment(
            id="wsl-llama.cpp",
            kind="wsl_runtime",
            name="WSL llama.cpp",
            available=True,
            binary_path=wsl,
            warnings=[f"WSL exists, but the llama-server probe failed: {exc}"],
        )

    return Environment(
        id="wsl-llama.cpp",
        kind="wsl_runtime",
        name="WSL llama.cpp",
        available=bool(binary),
        binary_path=binary,
        details={"wsl_binary": wsl, "probe": probe},
        warnings=[] if binary else ["WSL exists, but llama-server was not found in the default distro PATH."],
    )


def detect_all(project_root: Path | None = None, config: AppConfig | None = None) -> list[Environment]:
    return [
        detect_llama_cpp(project_root, config=config),
        detect_wsl_llama_cpp(),
        detect_ollama(),
        detect_lm_studio(),
        detect_vllm(),
        detect_wsl_vllm(config),
        detect_mlx(),
    ]


# Runtimes whose launch path is actually wired into prepare_launch_command.
# Others are detectable (and selectable in the UI) but cannot be started yet.
LAUNCHABLE_RUNTIMES = ("llama.cpp", "vllm-wsl")


def detect_runtime(
    runtime_id: str | None,
    project_root: Path | None = None,
    config: AppConfig | None = None,
) -> Environment | None:
    """Detect a single runtime by its environment id. Returns None if unknown."""

    if runtime_id in (None, "", "llama.cpp"):
        return detect_llama_cpp(project_root, config=config)
    if runtime_id == "wsl-llama.cpp":
        return detect_wsl_llama_cpp()
    if runtime_id == "vllm-wsl":
        return detect_wsl_vllm(config)
    detectors = {
        "ollama": detect_ollama,
        "lm-studio": detect_lm_studio,
        "vllm": detect_vllm,
        "mlx": detect_mlx,
    }
    detector = detectors.get(runtime_id)
    return detector() if detector else None
