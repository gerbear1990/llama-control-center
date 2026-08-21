from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any, Dict


def detect_hf_cli() -> Dict[str, Any]:
    """Detects if Hugging Face CLI is installed and returns its version."""
    binary = shutil.which("huggingface-cli")
    if not binary:
        return {
            "installed": False,
            "version": None,
            "binary_path": None,
            "install_guidance": "Run 'pip install huggingface_hub' to install the Hugging Face CLI.",
        }

    result = subprocess.run(
        [binary, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return {
            "installed": True,
            "version": "Unknown (error running --version)",
            "binary_path": binary,
            "error": result.stderr.strip(),
        }

    version = result.stdout.strip()
    return {
        "installed": True,
        "version": version,
        "binary_path": binary,
        "install_guidance": None,
    }


def check_for_updates() -> Dict[str, Any]:
    """Checks if the huggingface-cli needs an update by comparing with PyPI."""
    cli = detect_hf_cli()
    if not cli.get("installed"):
        return {"needs_update": False, "message": "Not installed."}

    current = cli.get("version", "")
    current_version = _extract_version(current)
    if not current_version:
        return {"needs_update": False, "message": "Cannot determine current version."}

    try:
        import urllib.request
        req = urllib.request.Request(
            "https://pypi.org/pypi/huggingface_hub/json",
            headers={"User-Agent": "llama-control-center"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            latest = data.get("info", {}).get("version", "")
    except Exception:
        return {"needs_update": False, "message": "Could not check PyPI."}

    if not latest:
        return {"needs_update": False, "message": "No version info from PyPI."}

    if _version_tuple(latest) > _version_tuple(current_version):
        return {
            "needs_update": True,
            "current_version": current_version,
            "latest_version": latest,
            "message": f"Update available: {current_version} → {latest}",
        }
    return {"needs_update": False, "message": "Up to date."}


def _extract_version(version_str: str) -> str | None:
    """Extract version number from a version string like 'huggingface-cli 0.30.0'."""
    match = re.search(r"(\d+\.\d+(?:\.\d+)?)", version_str)
    return match.group(1) if match else None


def _version_tuple(version_str: str) -> tuple:
    """Convert version string to comparable tuple."""
    try:
        return tuple(int(x) for x in version_str.split("."))
    except (ValueError, AttributeError):
        return (0,)
