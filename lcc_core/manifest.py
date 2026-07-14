from __future__ import annotations

import json
import re
from pathlib import Path, PureWindowsPath
from typing import Any

from .paths import find_project_root
from .schema import ModelProfile


MODEL_ASSIGNMENT_RE = re.compile(r"(?im)^\s*\$model\s*=\s*['\"]([^'\"]+)['\"]")
MODEL_ARG_RE = re.compile(r"(?im)(?:^|\s)-m['\"]?\s*,?\s*['\"]([^'\"]+\.gguf)['\"]")
WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _is_absolute_path_like(value: str) -> bool:
    if not value or "://" in value:
        return False
    return Path(value).is_absolute() or bool(WINDOWS_ABSOLUTE_RE.match(value)) or PureWindowsPath(value).is_absolute()


def _absolute_strings(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            results.extend(_absolute_strings(item, child_prefix))
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            results.extend(_absolute_strings(item, f"{prefix}[{idx}]"))
    elif isinstance(value, str) and _is_absolute_path_like(value):
        results.append((prefix, value))
    return results


def _parse_model_path(script_path: Path | None) -> str | None:
    if not script_path or not script_path.is_file():
        return None
    try:
        content = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for pattern in [MODEL_ASSIGNMENT_RE, MODEL_ARG_RE]:
        match = pattern.search(content)
        if match:
            return match.group(1)
    return None


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """Raw loader (bypasses safety). Internal / legacy only.

    All production read paths must go through load_manifest_safely (or
    load_profiles which now delegates to it) to avoid data-loss on corrupt
    models.json.
    """
    with manifest_path.open("r", encoding="utf-8") as f:
        return json.load(f)


class ManifestReadError(RuntimeError):
    """Raised when models.json cannot be read or parsed safely.

    Used by write paths (save/delete/profile-resolver) that must never
    silently reset the manifest — losing existing profile entries on a
    transient read failure (corrupt JSON, antivirus lock, partial write
    from a prior crash) is a destructive data-loss bug.
    """


def load_manifest_safely(manifest_path: Path) -> dict[str, Any]:
    """Read models.json; raise ManifestReadError on any read or parse failure.

    A missing file is treated as an empty manifest (correct for fresh
    setups). Anything else — JSON parse errors, OS errors, non-dict
    payloads, a non-list ``models`` field — surfaces as ``ManifestReadError``
    so callers can refuse to operate instead of silently overwriting
    user data with an empty list.
    """
    if not manifest_path.is_file():
        return {"models": []}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestReadError(
            f"models.json at {manifest_path} could not be read: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ManifestReadError(
            f"models.json at {manifest_path} is not a JSON object (got {type(data).__name__})"
        )
    models = data.setdefault("models", [])
    if not isinstance(models, list):
        raise ManifestReadError(
            f"models.json at {manifest_path} has a non-list 'models' field"
        )
    return data


def write_manifest_atomic(manifest_path: Path, manifest: dict[str, Any]) -> None:
    """Write models.json atomically via tmp+rename so a crash mid-write
    can't corrupt the file. Raises OSError on filesystem failure."""
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    tmp.replace(manifest_path)


def load_profiles(
    project_root: Path | None = None,
    manifest_path: Path | None = None,
) -> list[ModelProfile]:
    root = project_root or find_project_root()
    path = manifest_path or (root / "models.json" if root else None)
    if not path or not path.is_file():
        return []

    manifest = load_manifest_safely(path)
    profiles: list[ModelProfile] = []
    for entry in manifest.get("models", []) or []:
        script_name = entry.get("script")
        script_path = root / script_name if root and script_name else None
        if script_path and not script_path.is_file() and root:
            script_path = root / "scripts" / script_name
        # Modern non-GGUF runtimes can point directly at a checkpoint
        # directory and do not need a generated PowerShell launch script.
        model_path = entry.get("model_path") or _parse_model_path(script_path)
        recommended = entry.get("recommended_params", {}) or {}
        portable_warnings = []
        for location, value in _absolute_strings(recommended):
            portable_warnings.append(f"recommended_params.{location} contains an absolute path: {value}")
        if model_path and _is_absolute_path_like(model_path):
            portable_warnings.append(f"profile contains an absolute model path: {model_path}")

        model_exists = None
        if model_path:
            model_exists = Path(model_path).expanduser().exists()

        profiles.append(
            ModelProfile(
                mode=str(entry.get("mode", "")),
                name=str(entry.get("name", "")),
                description=str(entry.get("description", "")),
                script=script_name,
                script_path=str(script_path) if script_path else None,
                script_exists=bool(script_path and script_path.is_file()),
                model_path=model_path,
                model_exists=model_exists,
                model_size_gb=entry.get("model_size_gb"),
                recommended_params=recommended,
                portable_warnings=portable_warnings,
            )
        )
    return profiles
