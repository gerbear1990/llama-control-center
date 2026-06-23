from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - exercised by runtime import
    raise RuntimeError(
        "lcc_api requires fastapi and pydantic. Install dependencies with `pip install -r requirements.txt`."
    ) from exc

from lcc_core.benchmark import load_benchmark_results, run_profile_benchmark
from lcc_core.config import AppConfig
from lcc_core.estimates import enrich_profiles_with_fit_status, estimate_memory_fit, estimate_tokens_per_second
from lcc_core.fit import run_fit_test
from lcc_core.hardware import detect_system_hardware
from lcc_core.hf_cli import detect_hf_cli as hf_cli_detect, check_for_updates, install_hf_cli
from lcc_core.draft_models import suggest_draft_models, pull_draft_model, download_model_file
from lcc_core.inventory import build_inventory
from lcc_core.launch_scripts import (
    delete_launch_script,
    generate_all_launch_scripts,
    generate_launch_script,
    launch_scripts_scan_summary,
    list_launch_scripts,
    startup_autoscan_if_enabled,
)
from lcc_core.profile_resolver import resolved_inventory, resolve_profiles
from lcc_core.hf_metadata import fetch_model_info, check_model_update
from lcc_core.runtime_updates import check_runtime_updates
from lcc_core.sampling import list_sampling_intents, suggest_sampling
from lcc_core.server_manager import list_servers, prepare_launch_command, start_profile, stop_server
from lcc_core.smart_tune import auto_tune_fit


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Regenerate launch scripts for any new models at server startup."""

    try:
        startup_autoscan_if_enabled()
    except Exception:  # pragma: no cover - autoscan must never break startup
        pass
    yield


from lcc_api import __version__

app = FastAPI(title="Llama Control Center API", version=__version__, lifespan=_lifespan)
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
    extra_llama_args: list[str] = Field(default_factory=list)
    update_channel: str = "stable"
    server_history_limit: int = 5
    auto_generate_launch_scripts: bool = True
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
    data = config.model_dump() if hasattr(config, "model_dump") else config.dict()
    app_config = AppConfig(**data)
    path = app_config.save()
    return {"success": True, "path": str(path), "config": app_config.to_dict()}


@app.get("/api/inventory")
def get_inventory() -> dict[str, Any]:
    config = AppConfig.load()
    return build_inventory(model_dirs=[Path(path) for path in config.model_dirs] or None)


@app.post("/api/inventory")
def post_inventory(request: InventoryRequest) -> dict[str, Any]:
    return build_inventory(
        project_root=request.project_root,
        model_dirs=[Path(path) for path in request.model_dirs] or None,
    )


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
    profiles = [profile.to_dict() for profile in resolve_profiles(model_dirs=[Path(path) for path in config.model_dirs] or None)]
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
    from lcc_core.server_manager import prune_stale_servers, trim_server_history
    from lcc_core.config import AppConfig
    prune_stale_servers()
    config = AppConfig.load()
    trim_server_history(config.server_history_limit)
    return {"servers": list_servers()}


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
    profiles = resolve_profiles(project_root=request.project_root, model_dirs=model_dirs)
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
    profiles = resolve_profiles(project_root=request.project_root, model_dirs=model_dirs)
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
    profiles = resolve_profiles(project_root=request.project_root, model_dirs=model_dirs)
    profile = next((item for item in profiles if item.mode == request.mode), None)
    if not profile:
        raise HTTPException(status_code=400, detail=f"Unknown profile mode: {request.mode}")
    params = dict(profile.params)
    params.update(request.overrides or {})
    hardware = detect_system_hardware()
    speed_estimate = estimate_tokens_per_second(params, profile.model, hardware)
    fit_status = estimate_memory_fit(params, profile.model, hardware)
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


@app.post("/api/hf-cli/install")
def install_hf_cli_endpoint() -> dict[str, Any]:
    return install_hf_cli()


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

    root = find_project_root()
    if not root:
        return {"success": False, "message": "Could not find project root. Create a models.json file first."}
    manifest_path = root / "models.json"
    if not manifest_path.is_file():
        manifest = {"models": []}
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {"models": []}
    models = manifest.get("models", [])
    existing = next((m for m in models if m.get("mode") == request.mode), None)
    if existing is not None:
        existing["name"] = request.name
        existing["description"] = request.description
        existing["recommended_params"] = request.params
        message = f"Updated profile '{request.name}'."
    else:
        models.append({
            "mode": request.mode,
            "name": request.name,
            "description": request.description,
            "recommended_params": request.params,
        })
        message = f"Saved profile '{request.name}'."

    manifest["models"] = models
    tmp_path = manifest_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(manifest_path)
    return {"success": True, "message": message}


class GenerateLaunchScriptRequest(BaseModel):
    mode: str
    model_path: str
    params: dict[str, Any] = Field(default_factory=dict)
    name: str | None = None
    project_root: str | None = None
    overwrite: bool = True


@app.get("/api/launch-scripts")
def get_launch_scripts() -> dict[str, Any]:
    summary = launch_scripts_scan_summary()
    summary["success"] = True
    return summary


@app.post("/api/launch-scripts/generate")
def generate_single_launch_script(request: GenerateLaunchScriptRequest) -> dict[str, Any]:
    if not request.mode or not request.model_path:
        raise HTTPException(status_code=400, detail="mode and model_path are required.")
    try:
        payload = generate_launch_script(
            mode=request.mode,
            model_path=request.model_path,
            params=request.params,
            project_root=request.project_root,
            name=request.name,
            overwrite=request.overwrite,
        )
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload["success"] = True
    return payload


@app.post("/api/launch-scripts/scan")
def scan_launch_scripts() -> dict[str, Any]:
    """Trigger a fresh scan/regeneration of all launch scripts."""

    result = generate_all_launch_scripts()
    payload = result.to_dict()
    payload["success"] = True
    return payload


class LaunchScriptActionRequest(BaseModel):
    mode: str


@app.post("/api/launch-scripts/delete")
def delete_launch_script_endpoint(request: LaunchScriptActionRequest) -> dict[str, Any]:
    if not request.mode:
        raise HTTPException(status_code=400, detail="mode is required.")
    removed = delete_launch_script(request.mode)
    return {"success": True, "removed": removed, "mode": request.mode}
