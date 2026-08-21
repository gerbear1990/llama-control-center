from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - exercised by runtime import
    raise RuntimeError(
        "lcc_api requires fastapi and pydantic. Install dependencies with `pip install -r requirements.txt`."
    ) from exc

from lcc_core.benchmark import load_benchmark_results, run_profile_benchmark, send_chat_prompt
from lcc_core.config import AppConfig
from lcc_core.estimates import enrich_profiles_with_fit_status, estimate_memory_fit, estimate_tokens_per_second
from lcc_core.fit import run_fit_test
from lcc_core.hardware import detect_system_hardware
from lcc_core.hf_cli import detect_hf_cli as hf_cli_detect, check_for_updates
from lcc_core.draft_models import suggest_draft_models, pull_draft_model, download_model_file
from lcc_core.inventory import build_inventory
from lcc_core.profile_registry import (
    normalize_model_path,
    register_discovered_models,
    startup_autoscan_if_enabled,
)
from lcc_core.profile_resolver import resolved_inventory, resolve_profiles
from lcc_core.hf_metadata import fetch_model_info, check_model_update
from lcc_core.manifest import ManifestReadError
from lcc_core.runtime_updates import check_runtime_updates
from lcc_core.sampling import list_sampling_intents, suggest_sampling
from lcc_core.server_manager import list_servers, prepare_launch_command, start_profile, stop_server
from lcc_core.smart_tune import auto_tune_fit


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Register profiles for any new models at server startup."""

    try:
        startup_autoscan_if_enabled()
    except Exception:  # pragma: no cover - autoscan must never break startup
        pass
    yield


from lcc_api import __version__

app = FastAPI(title="Llama Control Center API", version=__version__, lifespan=_lifespan)

# CORS so browser apps (e.g. Auto-Editor Vite on :5173 / Electron) can call /api/servers.
# The regex covers every local port plus Electron's app:// origins. Opaque origins
# ("null", i.e. file:// and sandboxed iframes) are deliberately NOT allowed: this API
# is unauthenticated, so any website could otherwise drive it from a sandboxed frame.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|app://.*",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class InventoryRequest(BaseModel):
    project_root: str | None = None
    model_dirs: list[str] = Field(default_factory=list)


class StartRequest(BaseModel):
    mode: str
    project_root: str | None = None
    model_dirs: list[str] = Field(default_factory=list)
    overrides: dict[str, Any] = Field(default_factory=dict)
    stop_existing: bool = False
    wait_ready: bool = True
    ready_timeout_seconds: int = 45


class FitRequest(StartRequest):
    target_mib: int = 1024
    timeout_seconds: int = 180


class StopRequest(BaseModel):
    server_id: str | None = None
    mode: str | None = None


class ConfigRequest(BaseModel):
    model_dirs: list[str] = Field(default_factory=list)
    default_host: str = "127.0.0.1"
    default_port: int = 8080
    default_backend: str = "llama.cpp"
    runtime_dirs: list[str] = Field(default_factory=list)
    llama_server_path: str = ""
    llama_fit_params_path: str = ""
    wsl_distro: str = "Ubuntu-24.04"
    vllm_wsl_venv: str = "/opt/lcc-vllm"
    extra_llama_args: list[str] = Field(default_factory=list)
    update_channel: str = "stable"
    server_history_limit: int = 5
    auto_scan_on_startup: bool = True


class EstimateRequest(BaseModel):
    mode: str
    project_root: str | None = None
    model_dirs: list[str] = Field(default_factory=list)
    overrides: dict[str, Any] = Field(default_factory=dict)


class BenchmarkRequest(EstimateRequest):
    prompt: str | None = None
    completion_tokens: int = 128
    restart: bool = True
    stop_after: bool = False
    ready_timeout_seconds: int = 90


class HFInfoRequest(BaseModel):
    repo_id: str | None = None
    name: str | None = None
    path: str | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True}


@app.get("/api/meta")
def get_meta() -> dict[str, Any]:
    return {"version": app.version, "name": app.title}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return AppConfig.load().to_dict()


@app.post("/api/config")
def save_config(config: ConfigRequest) -> dict[str, Any]:
    # Merge onto the stored config instead of replacing it: fields the UI never
    # submits (profile_names, ignored_model_paths, the WSL paths) would otherwise
    # be reset to defaults on every Settings save.
    if hasattr(config, "model_dump"):
        submitted = config.model_dump(exclude_unset=True)
    else:  # pragma: no cover - pydantic v1 fallback
        submitted = config.dict(exclude_unset=True)
    app_config = AppConfig.load()
    for key, value in submitted.items():
        if key in AppConfig.__dataclass_fields__:
            setattr(app_config, key, value)
    path = app_config.save()
    return {"success": True, "path": str(path), "config": app_config.to_dict()}


@app.get("/api/inventory")
def get_inventory() -> dict[str, Any]:
    config = AppConfig.load()
    try:
        return build_inventory(model_dirs=[Path(path) for path in config.model_dirs] or None)
    except ManifestReadError as exc:
        return {"error": "manifest_read_error", "message": str(exc), "profiles": [], "models": []}


@app.post("/api/inventory")
def post_inventory(request: InventoryRequest) -> dict[str, Any]:
    try:
        return build_inventory(
            project_root=request.project_root,
            model_dirs=[Path(path) for path in request.model_dirs] or None,
        )
    except ManifestReadError as exc:
        return {"error": "manifest_read_error", "message": str(exc), "profiles": [], "models": []}


@app.get("/api/runtime-updates")
def get_runtime_updates() -> dict[str, Any]:
    config = AppConfig.load()
    inventory = build_inventory(model_dirs=[Path(path) for path in config.model_dirs] or None)
    return check_runtime_updates(
        inventory.get("environments") or [],
        channel=config.update_channel or "stable",
    )


@app.post("/api/runtime-updates/refresh")
def refresh_runtime_updates(runtime: str | None = None) -> dict[str, Any]:
    config = AppConfig.load()
    inventory = build_inventory(model_dirs=[Path(path) for path in config.model_dirs] or None)
    # No runtime -> recheck all; a single runtime -> bypass cache for just that one.
    return check_runtime_updates(
        inventory.get("environments") or [],
        channel=config.update_channel or "stable",
        force_refresh=runtime is None,
        force_runtime=runtime,
    )


@app.get("/api/profiles")
def get_profiles() -> dict[str, Any]:
    config = AppConfig.load()
    hardware = detect_system_hardware()
    try:
        profiles = [profile.to_dict() for profile in resolve_profiles(model_dirs=[Path(path) for path in config.model_dirs] or None)]
    except ManifestReadError as exc:
        return {"profiles": [], "launchable_count": 0, "error": "manifest_read_error", "message": str(exc)}
    profiles = enrich_profiles_with_fit_status(profiles, hardware)
    for profile in profiles:
        mode = profile.get("mode")
        if mode and mode in config.profile_names:
            profile["name"] = config.profile_names[mode]
    return {
        "profiles": profiles,
        "launchable_count": len([profile for profile in profiles if profile["launchable"]]),
    }


@app.get("/api/system")
def get_system() -> dict[str, Any]:
    return detect_system_hardware()


@app.get("/api/system/live")
def get_system_live() -> dict[str, Any]:
    from lcc_core.hardware import live_system_status
    return live_system_status()


@app.get("/api/system/check-port")
def check_port(port: int, host: str = "127.0.0.1") -> dict[str, Any]:
    """Probe a TCP port from the dashboard so the user sees a live status dot
    next to the Port field, instead of waiting for the next launch attempt
    to fail. Returns ``port_in_use_reason`` ("reserved" vs "in_use") so the
    UI can phrase the action button correctly — Windows machines with the
    default netsh config exclude 8080/8081 from bind and need a port above
    15200, not a kill-conflict suggestion.
    """
    from lcc_core.server_manager import (
        _next_free_port,
        _port_in_use_info,
        _probe_port,
    )

    safe_host = host.strip() or "127.0.0.1"
    safe_port = max(1, min(65535, int(port)))
    probe = _probe_port(safe_host, safe_port)
    payload: dict[str, Any] = {
        "host": safe_host,
        "port": safe_port,
        "free": probe["free"],
    }
    if not probe["free"]:
        reason = probe.get("reason", "in_use")
        payload["port_in_use_reason"] = reason
        if reason == "reserved":
            payload["reserved_range"] = probe.get("range")
            rng = probe.get("range") or {}
            payload["suggested_port"] = _next_free_port(
                safe_host, rng.get("end", safe_port) + 1,
            )
        else:
            payload["port_holder"] = _port_in_use_info(safe_host, safe_port)
            payload["suggested_port"] = _next_free_port(safe_host, safe_port + 1)
    return payload


@app.post("/api/profiles")
def post_profiles(request: InventoryRequest) -> dict[str, Any]:
    payload = resolved_inventory(
        project_root=request.project_root,
        model_dirs=[Path(path) for path in request.model_dirs] or None,
    )
    hardware = detect_system_hardware()
    payload["resolved_profiles"] = enrich_profiles_with_fit_status(payload.get("resolved_profiles", []), hardware)
    return payload


@app.post("/api/servers/prepare")
def prepare_server(request: StartRequest) -> dict[str, Any]:
    result = prepare_launch_command(
        mode=request.mode,
        project_root=request.project_root,
        model_dirs=[Path(path) for path in request.model_dirs] or None,
        overrides=request.overrides,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/api/servers")
def get_servers() -> dict[str, Any]:
    from lcc_core.server_manager import refresh_server_states, trim_server_history
    from lcc_core.config import AppConfig
    refresh_server_states()
    config = AppConfig.load()
    trim_server_history(config.server_history_limit)
    return {"servers": list_servers()}


@app.post("/api/servers/purge")
def purge_servers(only_non_running: bool = True, all: bool = False) -> dict[str, Any]:
    """Remove tracked server history entries (all of them, or only non-running)."""
    from lcc_core.server_manager import purge_server_history
    result = purge_server_history(only_non_running=only_non_running, all=all)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/api/servers/{server_id}/metrics")
def get_server_metrics(server_id: str) -> dict[str, Any]:
    from lcc_core.server_metrics import fetch_server_metrics
    result = fetch_server_metrics(server_id=server_id)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/api/servers/{server_id}/logs")
def get_server_logs(server_id: str, lines: int = 200) -> dict[str, Any]:
    """Return tail of stdout/stderr logs for a tracked server."""
    from lcc_core.server_manager import server_logs
    result = server_logs(server_id=server_id, lines=lines)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/servers/start")
def start_server(request: StartRequest) -> dict[str, Any]:
    result = start_profile(
        mode=request.mode,
        project_root=request.project_root,
        model_dirs=[Path(path) for path in request.model_dirs] or None,
        overrides=request.overrides,
        stop_existing=request.stop_existing,
        wait_ready=request.wait_ready,
        ready_timeout_seconds=request.ready_timeout_seconds,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/profiles/fit")
def fit_profile(request: FitRequest) -> dict[str, Any]:
    result = run_fit_test(
        mode=request.mode,
        project_root=request.project_root,
        model_dirs=[Path(path) for path in request.model_dirs] or None,
        overrides=request.overrides,
        target_mib=request.target_mib,
        timeout_seconds=request.timeout_seconds,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/profiles/auto-tune")
def auto_tune_profile(request: EstimateRequest) -> dict[str, Any]:
    config = AppConfig.load()
    model_dirs = [Path(path) for path in request.model_dirs] or [Path(path) for path in config.model_dirs] or None
    try:
        profiles = resolve_profiles(project_root=request.project_root, model_dirs=model_dirs)
    except ManifestReadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    profile = next((item for item in profiles if item.mode == request.mode), None)
    if not profile:
        raise HTTPException(status_code=400, detail=f"Unknown profile mode: {request.mode}")
    params = dict(profile.params)
    params.update(request.overrides or {})
    hardware = detect_system_hardware()
    target = int(params.get("fit_target_mib") or 1024)
    result = auto_tune_fit(params, profile.model, hardware, target_mib=target)
    result["mode"] = request.mode
    return result


@app.get("/api/sampling/presets")
def sampling_presets() -> dict[str, Any]:
    return {"intents": list_sampling_intents(),
            "presets": {item["key"]: suggest_sampling(item["key"]) for item in list_sampling_intents()}}


@app.post("/api/estimate/tokens-per-second")
def estimate_tps(request: EstimateRequest) -> dict[str, Any]:
    config = AppConfig.load()
    model_dirs = [Path(path) for path in request.model_dirs] or [Path(path) for path in config.model_dirs] or None
    try:
        profiles = resolve_profiles(project_root=request.project_root, model_dirs=model_dirs)
    except ManifestReadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    profile = next((item for item in profiles if item.mode == request.mode), None)
    if not profile:
        raise HTTPException(status_code=400, detail=f"Unknown profile mode: {request.mode}")
    params = dict(profile.params)
    params.update(request.overrides or {})
    hardware = detect_system_hardware()
    estimate = estimate_tokens_per_second(params, profile.model, hardware)
    return {
        "success": True,
        "mode": request.mode,
        "params": params,
        "model": profile.model,
        "hardware": hardware,
        "estimate": estimate,
    }


@app.post("/api/estimate/launch")
def estimate_launch(request: EstimateRequest) -> dict[str, Any]:
    config = AppConfig.load()
    model_dirs = [Path(path) for path in request.model_dirs] or [Path(path) for path in config.model_dirs] or None
    try:
        profiles = resolve_profiles(project_root=request.project_root, model_dirs=model_dirs)
    except ManifestReadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    profile = next((item for item in profiles if item.mode == request.mode), None)
    if not profile:
        raise HTTPException(status_code=400, detail=f"Unknown profile mode: {request.mode}")
    params = dict(profile.params)
    params.update(request.overrides or {})
    hardware = detect_system_hardware()
    speed_estimate = estimate_tokens_per_second(params, profile.model, hardware)
    fit_status = estimate_memory_fit(params, profile.model, hardware, probe_model=True)
    return {
        "success": True,
        "mode": request.mode,
        "params": params,
        "model": profile.model,
        "hardware": hardware,
        "speed_estimate": speed_estimate,
        "fit_status": fit_status,
    }


@app.get("/api/benchmarks")
def get_benchmarks() -> dict[str, Any]:
    return {"benchmarks": load_benchmark_results()}


@app.post("/api/benchmarks/run")
def run_benchmark(request: BenchmarkRequest) -> dict[str, Any]:
    result = run_profile_benchmark(
        mode=request.mode,
        project_root=request.project_root,
        model_dirs=[Path(path) for path in request.model_dirs] or None,
        overrides=request.overrides,
        prompt=request.prompt,
        completion_tokens=request.completion_tokens,
        restart=request.restart,
        stop_after=request.stop_after,
        ready_timeout_seconds=request.ready_timeout_seconds,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result


class TestPromptRequest(BaseModel):
    mode: str
    prompt: str = ""
    max_tokens: int = 256
    temperature: float = 0.7
    messages: list[dict] | None = None  # for multi-turn chat history


@app.post("/api/servers/test-prompt")
def test_prompt(request: TestPromptRequest) -> dict[str, Any]:
    result = send_chat_prompt(
        mode=request.mode,
        prompt=request.prompt,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        messages=request.messages,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/models/hf-info")
def hf_model_info(request: HFInfoRequest) -> dict[str, Any]:
    result = fetch_model_info(repo_id=request.repo_id, name=request.name, path=request.path)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result)
    return result


@app.post("/api/models/hf-update-check")
def hf_model_update_check(request: HFInfoRequest) -> dict[str, Any]:
    result = check_model_update(repo_id=request.repo_id, name=request.name, path=request.path)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result)
    return result


class ModelDownloadRequest(BaseModel):
    repo_id: str
    filename: str
    dest_dir: str


@app.post("/api/models/hf-download")
def hf_model_download(request: ModelDownloadRequest) -> dict[str, Any]:
    result = download_model_file(request.repo_id, request.filename, request.dest_dir)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/servers/stop")
def stop_server_endpoint(request: StopRequest) -> dict[str, Any]:
    if not request.server_id and not request.mode:
        raise HTTPException(status_code=400, detail="Provide server_id or mode.")
    result = stop_server(server_id=request.server_id, mode=request.mode)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result


@app.get("/api/hf-cli")
def get_hf_cli_status() -> dict[str, Any]:
    return hf_cli_detect()


class DraftModelRequest(BaseModel):
    model_name: str | None = None
    repo_id: str | None = None
    quant: str = "Q4_K_M"


@app.get("/api/draft-models/suggest")
def suggest_drafts(model_name: str | None = None) -> dict[str, Any]:
    suggestions = suggest_draft_models(model_name)
    return {"suggestions": suggestions}


@app.post("/api/draft-models/pull")
def pull_draft(request: DraftModelRequest) -> dict[str, Any]:
    if not request.repo_id:
        return {"success": False, "message": "repo_id is required."}
    return pull_draft_model(request.repo_id, request.quant)


@app.post("/api/hf-cli/check-updates")
def check_hf_updates() -> dict[str, Any]:
    return check_for_updates()


class ProfileNameRequest(BaseModel):
    mode: str
    name: str


class SaveProfileRequest(BaseModel):
    mode: str
    name: str
    description: str = ""
    model_path: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


@app.post("/api/profiles/name")
def save_profile_name(request: ProfileNameRequest) -> dict[str, Any]:
    config = AppConfig.load()
    config.profile_names[request.mode] = request.name
    config.save()
    return {"success": True, "mode": request.mode, "name": request.name}


@app.get("/api/profiles/names")
def get_profile_names() -> dict[str, Any]:
    config = AppConfig.load()
    return {"profile_names": config.profile_names}


@app.post("/api/profiles/save")
def save_profile(request: SaveProfileRequest) -> dict[str, Any]:
    from lcc_core.paths import find_project_root
    from lcc_core.manifest import (
        ManifestReadError,
        load_manifest_safely,
        write_manifest_atomic,
    )

    root = find_project_root()
    if not root:
        return {"success": False, "message": "Could not find project root. Create a models.json file first."}
    manifest_path = root / "models.json"
    # CRITICAL: never silently reset the manifest on a read failure. A
    # transient parse error or antivirus lock would otherwise wipe every
    # existing profile to a single empty list on the next save.
    try:
        manifest = load_manifest_safely(manifest_path)
    except ManifestReadError as exc:
        return {"success": False, "message": str(exc)}
    models = manifest.setdefault("models", [])
    existing = next((m for m in models if m.get("mode") == request.mode), None)
    if existing is not None:
        existing["name"] = request.name
        existing["description"] = request.description
        existing["recommended_params"] = request.params
        message = f"Updated profile '{request.name}'."
    else:
        entry = {
            "mode": request.mode,
            "name": request.name,
            "description": request.description,
            "recommended_params": request.params,
        }
        # Pin the model path when the client supplies one, so new entries
        # (e.g. save-as-copy) resolve by path instead of fuzzy name matching.
        if request.model_path:
            entry["model_path"] = str(request.model_path)
        models.append(entry)
        message = f"Saved profile '{request.name}'."

    manifest["models"] = models
    try:
        write_manifest_atomic(manifest_path, manifest)
    except OSError as exc:
        return {"success": False, "message": f"Failed to write models.json: {exc}"}

    # An explicit save is an intentional re-add: lift the delete tombstone so
    # scans can see this model again.
    model_path = str(request.model_path or (existing or {}).get("model_path") or "").strip()
    if model_path:
        config = AppConfig.load()
        key = normalize_model_path(model_path)
        remaining = [path for path in config.ignored_model_paths if normalize_model_path(path) != key]
        if len(remaining) != len(config.ignored_model_paths):
            config.ignored_model_paths = remaining
            config.save()
    return {"success": True, "message": message}


class DeleteProfileRequest(BaseModel):
    mode: str


@app.post("/api/profiles/delete")
def delete_profile(request: DeleteProfileRequest) -> dict[str, Any]:
    """Remove a profile entry from ``models.json``.

    Uses the same atomic tmp+replace write as ``/api/profiles/save`` so a
    partial write can't corrupt the manifest. Renamed profiles live in the
    user config (``profile_names``); the user may rename or remove them
    independently. Refuses to delete a profile whose tracked server is
    still running so Stop always wins.
    """
    from lcc_core.paths import find_project_root
    from lcc_core.server_manager import list_servers
    from lcc_core.manifest import (
        ManifestReadError,
        load_manifest_safely,
        write_manifest_atomic,
    )

    root = find_project_root()
    if not root:
        return {"success": False, "message": "Could not find project root."}
    manifest_path = root / "models.json"
    if not manifest_path.is_file():
        return {"success": False, "message": f"Unknown profile mode: {request.mode}"}

    # Refuse if a tracked server is still running for this profile so the user
    # can't accidentally lose the connection mid-generation.
    for server in list_servers():
        if server.get("mode") == request.mode and server.get("running"):
            return {
                "success": False,
                "message": f"Profile '{request.mode}' has a tracked server running. Stop it before deleting.",
            }

    try:
        manifest = load_manifest_safely(manifest_path)
    except ManifestReadError as exc:
        return {"success": False, "message": str(exc)}

    models = manifest.get("models", [])
    removed = next((m for m in models if m.get("mode") == request.mode), None)
    kept = [m for m in models if m.get("mode") != request.mode]
    if removed is None:
        return {"success": False, "message": f"Unknown profile mode: {request.mode}"}

    manifest["models"] = kept
    try:
        write_manifest_atomic(manifest_path, manifest)
    except OSError as exc:
        return {"success": False, "message": f"Failed to write models.json: {exc}"}

    # Also drop any custom name the user assigned for this mode.
    config = AppConfig.load()
    config_dirty = False
    if request.mode in config.profile_names:
        config.profile_names.pop(request.mode, None)
        config_dirty = True
    # Tombstone the model file. The GGUF stays on disk, so without this the next
    # autoscan (or manual scan) registers a fresh profile for the same model.
    model_path = str(removed.get("model_path") or "").strip()
    if model_path:
        known = {normalize_model_path(path) for path in config.ignored_model_paths}
        if normalize_model_path(model_path) not in known:
            config.ignored_model_paths.append(model_path)
            config_dirty = True
    if config_dirty:
        config.save()

    return {"success": True, "message": f"Deleted profile '{request.mode}'.", "mode": request.mode}


class ScanRequest(BaseModel):
    model_path: str | None = None


@app.post("/api/profiles/scan")
def scan_profiles(request: ScanRequest = ScanRequest()) -> dict[str, Any]:
    """Register newly discovered models as launchable profiles.

    When ``model_path`` is set, only that file is considered — a row Register
    must not enroll every new model on disk.
    """
    only = [request.model_path] if request.model_path else None
    result = register_discovered_models(only_paths=only)
    payload = result.to_dict()
    payload["success"] = True
    return payload
