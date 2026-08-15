from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from .paths import default_model_dirs, dedupe_paths
from .schema import ModelFile


QUANT_RE = re.compile(
    r"(?i)(?:^|[-_.])((?:i?q\d(?:_[a-z0-9]+)+)|(?:f16|bf16|f32))(?:[-_.]|$)"
)
PARAM_RE = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*([bm])(?:[-_\s]|$)")
SPLIT_RE = re.compile(r"(?i)^(?P<base>.+)-(?P<part>\d{5})-of-(?P<total>\d{5})\.gguf$")
GENERIC_MODEL_DIR_NAMES = {"gguf", "model", "models", "mtp", "weights"}
NON_LLM_MODEL_DIR_NAMES = {"controlnet", "diffusion_models", "loras", "unet", "vae"}


def _model_id(path: Path) -> str:
    raw = str(path).encode("utf-8", errors="replace")
    return hashlib.sha1(raw).hexdigest()[:16]


def _safe_mtime(path: Path) -> float | None:
    """Unix mtime of ``path`` or None when the stat fails (race, permissions).

    The gguf_meta_cache already keys on ``(size, mtime)`` so the dashboard's
    Updated column piggybacks on a stat the backend is making anyway.
    """
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _safe_size(path: Path) -> int | None:
    """Byte size of ``path`` or None when the stat fails (race, permissions).

    A split part can vanish or get locked between the walk and the stat; one
    OSError must not abort the whole scan.
    """
    try:
        return path.stat().st_size
    except OSError:
        return None


def parse_quant(filename: str) -> str | None:
    match = QUANT_RE.search(filename)
    if not match:
        return None
    return match.group(1).upper()


def parse_params(text: str) -> float | None:
    match = PARAM_RE.search(text)
    if not match:
        return None
    value = float(match.group(1))
    suffix = match.group(2).lower()
    return value if suffix == "b" else value / 1000.0


def _find_mmproj(directory: Path) -> str | None:
    if not directory.is_dir():
        return None
    for child in directory.iterdir():
        if child.is_file() and child.suffix.lower() == ".gguf" and "mmproj" in child.name.lower():
            return str(child)
    return None


def _split_info(path: Path) -> tuple[bool, int | None, list[Path]]:
    match = SPLIT_RE.match(path.name)
    if not match:
        return False, None, [path]
    part = int(match.group("part"))
    total = int(match.group("total"))
    pattern = f"{match.group('base')}-*-of-{match.group('total')}.gguf"
    parts = sorted(path.parent.glob(pattern))
    return part != 1, total, parts or [path]


def _source_name(path: Path, roots: list[tuple[str, Path]]) -> str:
    for source, root in roots:
        try:
            path.resolve().relative_to(root.resolve())
            return source
        except (OSError, ValueError):
            continue
    return "custom"


def _discover_transformers_dir(
    directory: Path,
    filenames: list[str],
    roots: list[tuple[str, Path]],
) -> ModelFile | None:
    """Return one model entry for a Hugging Face Transformers checkpoint.

    A config.json plus model*.safetensors is deliberately required so image
    checkpoints, LoRAs, VAEs, and other unrelated safetensors in a broad model
    root are not presented as launchable LLMs.
    """

    names = set(filenames)
    shard_names = sorted(name for name in filenames if re.match(r"(?i)^model(?:-\d+-of-\d+)?\.safetensors$", name))
    if "config.json" not in names or not shard_names:
        return None
    config_path = directory / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    architectures = [str(value) for value in (config.get("architectures") or [])]
    architecture_text = " ".join(architectures).lower()
    supported_architecture = any(
        marker in architecture_text
        for marker in ("forcausallm", "forconditionalgeneration", "forvision2seq", "forimagetexttotext")
    )
    if not supported_architecture:
        return None

    shards = [directory / name for name in shard_names]
    try:
        size = sum(path.stat().st_size for path in shards)
    except OSError:
        return None
    quant_text = json.dumps(config.get("quantization_config", {}), sort_keys=True).lower()
    quant = "NVFP4" if "nvfp4" in quant_text or "nvfp4" in directory.name.lower() else None
    warnings: list[str] = []
    index_path = directory / "model.safetensors.index.json"
    if len(shards) > 1 and not index_path.is_file():
        warnings.append("Sharded safetensors checkpoint has no model.safetensors.index.json.")

    return ModelFile(
        id=_model_id(directory),
        name=directory.name,
        path=str(directory),
        source=_source_name(directory, roots),
        format="Safetensors",
        size_bytes=size,
        quant=quant,
        params_b=parse_params(directory.name),
        mtime=max((_safe_mtime(path) or 0 for path in shards), default=0) or None,
        details={
            "config": str(config_path),
            "model_type": config.get("model_type"),
            "architectures": architectures,
            "shard_count": len(shards),
            "root": str(next((root for _, root in roots if directory == root or root in directory.parents), directory)),
        },
        warnings=warnings,
    )


def discover_models(
    model_dirs: list[Path] | None = None,
    project_root: Path | None = None,
    max_files: int = 10000,
) -> list[ModelFile]:
    """Discover local model files without scanning broad user directories."""

    if model_dirs is None:
        roots = default_model_dirs(project_root)
    else:
        roots = [("custom", path) for path in dedupe_paths(model_dirs) if path.is_dir()]

    discovered: list[ModelFile] = []
    seen: set[str] = set()
    visited = 0

    for _, root in roots:
        if not root.is_dir():
            continue
        for current_root, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                name
                for name in dirnames
                if not name.startswith(".") and name.lower() not in NON_LLM_MODEL_DIR_NAMES
            ]
            directory = Path(current_root)
            transformers_model = _discover_transformers_dir(directory, filenames, roots)
            if transformers_model is not None:
                key = str(directory.resolve())
                if key not in seen:
                    seen.add(key)
                    visited += 1
                    discovered.append(transformers_model)
                    if visited > max_files:
                        return sorted(discovered, key=lambda item: item.name.lower())
            for filename in filenames:
                if not filename.lower().endswith(".gguf"):
                    continue
                path = Path(current_root) / filename
                if "mmproj" in filename.lower():
                    continue
                skip_split_part, split_total, split_parts = _split_info(path)
                if skip_split_part:
                    continue
                try:
                    key = str(path.resolve())
                except OSError:
                    key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                visited += 1
                if visited > max_files:
                    return sorted(discovered, key=lambda item: item.name.lower())

                parent = path.parent
                size = sum(_safe_size(part) or 0 for part in split_parts)
                file_stem = path.stem
                if split_total:
                    split_match = SPLIT_RE.match(path.name)
                    file_stem = split_match.group("base") if split_match else file_stem
                if parent == root or parent.name.lower() in GENERIC_MODEL_DIR_NAMES:
                    name = file_stem
                else:
                    name = parent.name
                source = _source_name(path, roots)
                param_hint = parse_params(f"{parent.name} {file_stem}")
                warnings: list[str] = []
                if split_total and len(split_parts) < split_total:
                    warnings.append(f"Split GGUF appears incomplete: found {len(split_parts)} of {split_total} parts.")

                discovered.append(
                    ModelFile(
                        id=_model_id(path),
                        name=name,
                        path=str(path),
                        source=source,
                        format="GGUF",
                        size_bytes=size,
                        quant=parse_quant(path.name),
                        params_b=param_hint,
                        mmproj_path=_find_mmproj(parent),
                        split_total=split_total,
                        mtime=_safe_mtime(path),
                        details={"primary_file": path.name, "root": str(root)},
                        warnings=warnings,
                    )
                )

    return sorted(discovered, key=lambda item: item.name.lower())
