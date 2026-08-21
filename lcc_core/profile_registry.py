"""Register newly discovered models as launchable profiles in models.json.

Historically this was a side effect of launch-script generation
(``lcc_core.launch_scripts``, since removed): every scan wrote a .ps1/.sh
pair per model and registered brand-new models in models.json. The web UI
never executed those scripts -- it builds the llama-server command directly
via ``lcc_core.server_manager`` -- so only the registration behavior lives
on here. Entries are pinned by explicit ``model_path``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .manifest import ManifestReadError, load_manifest_safely, write_manifest_atomic
from .models import discover_models
from .paths import find_project_root
from .profile_resolver import resolve_profiles

SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")

MANIFEST_PARAM_KEYS = (
    "runtime",
    "ctx_size",
    "threads",
    "threads_batch",
    "batch_size",
    "ubatch_size",
    "gpu_layers",
    "cache_type_k",
    "cache_type_v",
    "flash_attn",
    "reasoning",
    "reasoning_budget",
    "cache_ram_mib",
    "cache_reuse",
    "slot_prompt_similarity",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_slug(value: str, fallback: str = "model") -> str:
    slug = SAFE_FILENAME_RE.sub("-", value or "").strip("-").lower()
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or fallback


def _norm_path(value: str) -> str:
    try:
        return str(Path(value).expanduser().resolve()).lower()
    except OSError:
        return str(value or "").lower()


def normalize_model_path(value: str) -> str:
    """Comparison key for model paths (resolved, lowercased for Windows)."""
    return _norm_path(value)


def _is_draft_model(model_path: str) -> bool:
    """Heuristically detect speculative/draft companion models.

    These are consumed via a profile's ``draft_model`` parameter and must
    not be registered as standalone server profiles. A path segment of
    ``mtp`` / ``draft``, a ``mtp-`` / ``draft-`` filename prefix, or a
    ``-draft-`` token is a companion. ``-MTP-`` in the middle of a product
    name (e.g. NVFP4-MTP-Q8attn) is not.
    """
    path = Path(model_path)
    parts = {segment.lower() for segment in path.parts[:-1]}
    if "mtp" in parts or "draft" in parts:
        return True
    name = path.name.lower()
    if re.match(r"(?:mtp|draft)[-_.]", name):
        return True
    if re.search(r"[-_.]draft[-_.]", name) or re.search(r"[-_.]draft\.gguf$", name):
        return True
    if re.search(r"[-_.]mtp\.gguf$", name):
        return True
    return False


def _manifest_params(params: dict[str, Any]) -> dict[str, Any]:
    """Trim a full param set down to the keys stored in models.json."""
    return {key: params[key] for key in MANIFEST_PARAM_KEYS if key in params}


def _default_params_for_model(model: dict[str, Any], config: AppConfig) -> dict[str, Any]:
    """Pick a reasonable starting parameter set for a freshly discovered model."""
    params: dict[str, Any] = {
        "host": config.default_host or "127.0.0.1",
        "port": int(config.default_port or 8080),
        "alias": Path(model.get("path", "")).stem or model.get("name", "local-model"),
        "ctx_size": 8192,
        "threads": 4,
        "threads_batch": 4,
        "batch_size": 512,
        "ubatch_size": 512,
        "gpu_layers": 999,
        "cache_type_k": "q4_0",
        "cache_type_v": "q4_0",
        "flash_attn": True,
        "kv_offload": True,
        "op_offload": True,
        "acceleration_backend": "auto",
        "device": "auto",
        "mmap": True,
        "reasoning": False,
    }
    params.update(_autotune_params_from_size(model, params))
    return params


def _autotune_params_from_size(model: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Tweak defaults based on the model size/quant so the first run fits."""
    overrides: dict[str, Any] = {}
    params_b = model.get("params_b")
    size_bytes = model.get("size_bytes") or 0
    if params_b:
        try:
            params_b = float(params_b)
        except (TypeError, ValueError):
            params_b = None
    if params_b is None and size_bytes:
        # Rough fallback: assume Q4_0 (~4.5 bits/param).
        params_b = max(0.5, (size_bytes * 8) / (4.5 * 1e9))

    if params_b and params_b >= 12:
        overrides["ctx_size"] = 16384
        overrides["batch_size"] = 1024
        overrides["ubatch_size"] = 512
    elif params_b and params_b <= 3:
        overrides["ctx_size"] = 8192
    return overrides


@dataclass
class RegisteredProfile:
    """A profile entry this scan added to models.json."""

    mode: str
    name: str
    model_path: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScanResult:
    """Summary of a registration pass for the API/UI."""

    registered: list[RegisteredProfile] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    scanned_model_count: int = 0
    profile_count: int = 0
    scanned_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "registered": [item.to_dict() for item in self.registered],
            "skipped": list(self.skipped),
            "errors": list(self.errors),
            "scanned_model_count": int(self.scanned_model_count),
            "profile_count": int(self.profile_count),
            "scanned_at": self.scanned_at,
            "registered_count": len(self.registered),
        }


def register_discovered_models(
    *,
    project_root: str | Path | None = None,
    model_dirs: list[str | Path] | None = None,
    config: AppConfig | None = None,
    only_paths: list[str | Path] | None = None,
) -> ScanResult:
    """Scan model folders and register any brand-new model as a profile.

    A corrupt models.json surfaces as a result error and aborts the pass:
    we'd rather refuse to write than silently overwrite existing profiles
    with an empty list.
    """
    app_config = config or AppConfig.load()
    root = Path(project_root).expanduser().resolve() if project_root else find_project_root()
    if model_dirs:
        parsed_model_dirs = [Path(path).expanduser() for path in model_dirs]
    elif app_config.model_dirs:
        parsed_model_dirs = [Path(path).expanduser() for path in app_config.model_dirs]
    else:
        parsed_model_dirs = None

    result = ScanResult(scanned_at=_now())

    try:
        resolved_profiles = resolve_profiles(project_root=root, model_dirs=parsed_model_dirs)
    except ManifestReadError as exc:
        result.errors.append({"mode": "models.json", "error": str(exc)})
        return result

    discovered_models = discover_models(parsed_model_dirs, root)
    result.scanned_model_count = len(discovered_models)
    result.profile_count = len(resolved_profiles)

    manifest_path = (Path(root) / "models.json") if root else None
    if not manifest_path:
        result.skipped.append({"mode": "*", "reason": "No project root; nothing to register into."})
        return result
    try:
        manifest_doc = load_manifest_safely(manifest_path)
    except ManifestReadError as exc:
        result.errors.append({"mode": "models.json", "error": str(exc)})
        return result

    manifest_models = manifest_doc["models"]
    manifest_dirty = False

    ignored_model_paths: set[str] = {
        _norm_path(path) for path in (app_config.ignored_model_paths or []) if str(path).strip()
    }
    handled_modes: set[str] = {profile.mode for profile in resolved_profiles}
    handled_model_paths: set[str] = set()
    draft_paths: set[str] = set()
    for profile in resolved_profiles:
        draft_model = str(profile.params.get("draft_model", "")).strip()
        if draft_model:
            draft_paths.add(_norm_path(draft_model))
        pinned = str((profile.profile or {}).get("model_path") or "").strip()
        if pinned:
            handled_model_paths.add(_norm_path(pinned))
        elif profile.model and profile.model.get("path"):
            handled_model_paths.add(_norm_path(profile.model["path"]))

    only = {_norm_path(path) for path in (only_paths or []) if str(path).strip()}

    for model in discovered_models:
        resolved_path = _norm_path(model.path)
        if only and resolved_path not in only:
            continue
        if resolved_path in handled_model_paths:
            continue
        if resolved_path in ignored_model_paths:
            result.skipped.append(
                {
                    "mode": _safe_slug(model.name or Path(model.path).stem),
                    "reason": "Profile was deleted by the user; save a profile for this model to register it again.",
                }
            )
            continue
        if str(model.format).upper() != "GGUF":
            result.skipped.append(
                {
                    "mode": _safe_slug(model.name or Path(model.path).stem),
                    "reason": "Non-GGUF checkpoint requires an explicit non-llama.cpp runtime profile.",
                }
            )
            continue
        if resolved_path in draft_paths or _is_draft_model(model.path):
            result.skipped.append(
                {
                    "mode": _safe_slug(model.name or Path(model.path).stem),
                    "reason": "Draft/speculative companion model; not registered as a standalone profile.",
                }
            )
            continue
        mode = _safe_slug(model.name or Path(model.path).stem)
        if mode in handled_modes:
            # Two models collapsed to the same slug; disambiguate with a short hash.
            mode = f"{mode}-{model.id[:6]}"
        params = _default_params_for_model(model.to_dict(), app_config)
        new_entry = {
            "mode": mode,
            "name": model.name or mode,
            "description": "Auto-generated from discovered model",
            "model_path": model.path,
            "recommended_params": _manifest_params(params),
        }
        manifest_models.append(new_entry)
        manifest_dirty = True
        result.registered.append(
            RegisteredProfile(mode=mode, name=new_entry["name"], model_path=model.path, params=params)
        )
        handled_modes.add(mode)
        handled_model_paths.add(resolved_path)

    if manifest_dirty:
        manifest_doc["models"] = manifest_models
        try:
            write_manifest_atomic(manifest_path, manifest_doc)
        except OSError as exc:
            result.errors.append({"mode": "models.json", "error": str(exc)})

    return result


def startup_autoscan_if_enabled(config: AppConfig | None = None) -> ScanResult | None:
    """Run a startup registration scan if the user has it enabled."""
    app_config = config or AppConfig.load()
    if not app_config.auto_scan_on_startup:
        return None
    return register_discovered_models(config=app_config)


__all__ = [
    "RegisteredProfile",
    "ScanResult",
    "normalize_model_path",
    "register_discovered_models",
    "startup_autoscan_if_enabled",
]
