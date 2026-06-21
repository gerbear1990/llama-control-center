from __future__ import annotations

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
from lcc_core.draft_models import suggest_draft_models, detect_hf_cli as draft_detect_hf_cli, pull_draft_model
from lcc_core.inventory import build_inventory
from lcc_core.profile_resolver import resolved_inventory, resolve_profiles
from lcc_core.runtime_updates import check_runtime_updates
from lcc_core.server_manager import list_servers, prepare_launch_command, server_logs, start_profile, stop_server


app = FastAPI(title="Llama Control Center API", version="0.4.0")
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
def refresh_runtime_updates() -> dict[str, Any]:
    config = AppConfig.load()
    inventory = build_inventory(model_dirs=[Path(path) for path in config.model_dirs] or None)
    return check_runtime_updates(
        inventory.get("environments") or [],
        channel=config.update_channel or "stable",
        force_refresh=True,
    )


@app.get("/api/profiles")
def get_profiles() -> dict[str, Any]:
    config = AppConfig.load()
    hardware = detect_system_hardware()
    profiles = [profile.to_dict() for profile in resolve_profiles(model_dirs=[Path(path) for path in config.model_dirs] or None)]
    profiles = enrich_profiles_with_fit_status(profiles, hardware)
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
