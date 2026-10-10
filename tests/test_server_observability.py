"""The metrics panel must read what the installed llama-server actually exports.

Found 2026-10-02 against build b10752: LCC launched without --metrics (so
/metrics returned 501 and every summary field was null), the alias table
matched 3 of 15 exported names, and props reported context_length from
``total_slots`` (4) while n_ctx sat unread under default_generation_settings.
The payloads below are captured verbatim from that build.
"""
from __future__ import annotations

from lcc_core import server_metrics
from lcc_core.llama_args import build_llama_server_args

B10752_METRICS = """\
# HELP llamacpp:prompt_tokens_total Number of prompt tokens processed.
# TYPE llamacpp:prompt_tokens_total counter
llamacpp:prompt_tokens_total 21
llamacpp:prompt_tokens_cached_total 0
llamacpp:prompt_seconds_total 0.257967
llamacpp:tokens_predicted_total 150
llamacpp:tokens_predicted_seconds_total 2.49684
llamacpp:n_decode_total 151
llamacpp:n_tokens_max 170
llamacpp:prompt_tokens_seconds 81.4058
llamacpp:predicted_tokens_seconds 59.6755
llamacpp:requests_processing 1
llamacpp:requests_deferred 2
llamacpp:n_busy_slots_per_decode 1
"""

B10752_PROPS = {
    "default_generation_settings": {"n_ctx": 131072},
    "total_slots": 4,
    "model_alias": "qwen3.8-27b-gguf",
    "model_path": "C:\\models\\Qwen3.8-27B-UD-Q5_K_XL.gguf",
    "build_info": "b10752-b96806d96",
}


def _fetch(monkeypatch, metrics_text):
    server = {"id": "s1", "mode": "m", "pid": 123, "host": "127.0.0.1", "port": 8080, "runtime": "llama.cpp"}
    monkeypatch.setattr(server_metrics, "_find_server", lambda sid, mode: server)
    monkeypatch.setattr(server_metrics, "pid_is_running", lambda pid: True)
    monkeypatch.setattr(server_metrics, "_process_memory", lambda pid: {"rss_bytes": 1, "cpu_percent": None})
    monkeypatch.setattr(server_metrics, "_compute_apps_vram", lambda: {})

    def get_text(url):
        if url.endswith("/metrics"):
            if metrics_text is None:
                raise OSError("HTTP Error 501: Not Implemented")
            return metrics_text
        return "{\"status\":\"ok\"}"

    monkeypatch.setattr(server_metrics, "_get_text", get_text)
    monkeypatch.setattr(server_metrics, "_get_json", lambda url: B10752_PROPS)
    return server_metrics.fetch_server_metrics("s1")


def test_launch_enables_the_metrics_endpoint():
    cmd = build_llama_server_args("llama-server", "m.gguf", {"gpu_layers": 999})
    assert "--metrics" in cmd.argv


def test_current_metric_names_reach_the_summary(monkeypatch):
    summary = _fetch(monkeypatch, B10752_METRICS)["summary"]
    assert summary["predicted_tokens_per_second"] == 59.6755
    assert summary["prompt_tokens_per_second"] == 81.4058
    assert summary["slots_processing"] == 1


def test_props_read_context_and_model_from_where_the_build_puts_them(monkeypatch):
    props = _fetch(monkeypatch, B10752_METRICS)["props"]
    assert props["n_ctx"] == 131072
    assert props["context_length"] == 131072
    assert props["total_slots"] == 4
    assert props["model_name"] == "qwen3.8-27b-gguf"


def test_metrics_endpoint_off_is_reported_not_silently_empty(monkeypatch):
    on = _fetch(monkeypatch, B10752_METRICS)
    off = _fetch(monkeypatch, None)
    assert on["metrics_available"] is True
    assert off["metrics_available"] is False
