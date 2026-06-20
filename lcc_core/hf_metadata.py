from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


HF_API = "https://huggingface.co/api"
HF_BASE = "https://huggingface.co"


def _headers() -> dict[str, str]:
    headers = {"User-Agent": "llama-control-center/0.1"}
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _get_json(url: str, timeout: float = 10.0) -> Any:
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_text(url: str, timeout: float = 10.0) -> str:
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def infer_query(name: str | None = None, path: str | None = None) -> str:
    parts = [name or ""]
    if path:
        path_obj = Path(path)
        parts.extend([path_obj.stem, path_obj.parent.name])
    query = " ".join(parts)
    query = re.sub(r"(?i)\b(gguf|unsloth|thebloke|q\d(?:_[a-z0-9]+)+|ud|it)\b", " ", query)
    query = re.sub(r"[-_]+", " ", query)
    query = re.sub(r"\s+", " ", query).strip()
    return query or (name or Path(path or "").stem)


def _strip_markdown(markdown: str) -> str:
    text = re.sub(r"(?s)^---.*?---", "", markdown).strip()
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[[^\]]*\]\([^)]+\)", lambda match: match.group(0).split("]")[0].lstrip("["), text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*]\s+", "", text)
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    clean = [p for p in paragraphs if len(p) > 80 and not p.lower().startswith(("license", "usage", "installation"))]
    return "\n\n".join(clean[:2])[:1200]


def _readme_summary(model_id: str) -> str | None:
    for branch in ["main", "master"]:
        url = f"{HF_BASE}/{model_id}/raw/{branch}/README.md"
        try:
            text = _get_text(url, timeout=8.0)
        except Exception:
            continue
        summary = _strip_markdown(text)
        if summary:
            return summary
    return None


def search_models(query: str, limit: int = 5) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote(query)
    url = f"{HF_API}/models?search={encoded}&sort=downloads&direction=-1&limit={int(limit)}"
    payload = _get_json(url)
    if not isinstance(payload, list):
        return []
    return payload


def fetch_model_info(repo_id: str | None = None, name: str | None = None, path: str | None = None) -> dict[str, Any]:
    query = repo_id or infer_query(name, path)
    try:
        if repo_id:
            model = _get_json(f"{HF_API}/models/{urllib.parse.quote(repo_id, safe='/')}")
            matches = [model] if isinstance(model, dict) else []
        else:
            matches = search_models(query, limit=6)
    except Exception as exc:
        return {"success": False, "query": query, "error": str(exc), "matches": []}

    if not matches:
        return {"success": False, "query": query, "error": "No Hugging Face models found.", "matches": []}

    model = matches[0]
    model_id = model.get("modelId") or model.get("id")
    summary = _readme_summary(model_id) if model_id else None
    card_data = model.get("cardData") or {}
    tags = model.get("tags") or []

    return {
        "success": True,
        "query": query,
        "model_id": model_id,
        "url": f"{HF_BASE}/{model_id}" if model_id else None,
        "summary": summary or card_data.get("summary") or model.get("description") or "",
        "downloads": model.get("downloads"),
        "likes": model.get("likes"),
        "pipeline_tag": model.get("pipeline_tag"),
        "library_name": model.get("library_name"),
        "tags": tags[:20],
        "card_data": card_data,
        "matches": [
            {
                "model_id": item.get("modelId") or item.get("id"),
                "downloads": item.get("downloads"),
                "likes": item.get("likes"),
                "tags": (item.get("tags") or [])[:10],
            }
            for item in matches[:6]
        ],
    }

