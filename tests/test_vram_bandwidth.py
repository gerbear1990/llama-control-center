"""VRAM bandwidth feeds the tokens/sec ceiling, so it must match the card.

Found 2026-10-02: an RTX 5090 was detected at 672 GB/s (real: 1792) and the
TPS estimate reported 37 t/s at "high" confidence against 57 measured. Two
errors multiplied: the name table said 384-bit (it is 512), and nvidia-smi's
memory clock (14001 MHz) was used as the data rate, which is half the
effective rate for GDDR5X/6/6X/7 and HBM.
"""
from __future__ import annotations

import subprocess

import pytest

from lcc_core import hardware

# Published bus widths. Ordering traps: "5070 ti" vs "5070", "3080 ti" vs "3080",
# "a100" vs "a10", "l40" vs "l4", "2060 super" vs "2060".
WIDTHS = [
    ("NVIDIA GeForce RTX 5090", 512),
    ("NVIDIA GeForce RTX 5080", 256),
    ("NVIDIA GeForce RTX 5070 Ti", 256),
    ("NVIDIA GeForce RTX 5070", 192),
    ("NVIDIA GeForce RTX 5060 Ti", 128),
    ("NVIDIA GeForce RTX 4090", 384),
    ("NVIDIA GeForce RTX 4070 Ti SUPER", 256),
    ("NVIDIA GeForce RTX 4070 Ti", 192),
    ("NVIDIA GeForce RTX 3090", 384),
    ("NVIDIA GeForce RTX 3080 Ti", 384),
    ("NVIDIA GeForce RTX 3080", 320),
    ("NVIDIA GeForce RTX 3070", 256),
    ("NVIDIA GeForce RTX 3060 Ti", 256),
    ("NVIDIA GeForce RTX 3060", 192),
    ("NVIDIA GeForce RTX 2080 Ti", 352),
    ("NVIDIA GeForce RTX 2060 SUPER", 256),
    ("NVIDIA GeForce RTX 2060", 192),
    ("NVIDIA GeForce GTX 1080 Ti", 352),
    ("NVIDIA A100-SXM4-80GB", 5120),
    ("NVIDIA A10", 384),
    ("NVIDIA L40S", 384),
    ("NVIDIA L4", 192),
]


@pytest.mark.parametrize("name,bits", WIDTHS)
def test_bus_width_matches_published_spec(name, bits):
    assert hardware._nvidia_bus_width_from_name(name) == bits


def test_unknown_card_has_no_guess():
    assert hardware._nvidia_bus_width_from_name("NVIDIA Quadro Mystery") is None


def test_rtx_5090_bandwidth_from_nvidia_smi(monkeypatch):
    line = "0, NVIDIA GeForce RTX 5090, 32607, 30000, 581.29, 14001, 14001\n"
    monkeypatch.setattr(hardware.shutil, "which", lambda name: "nvidia-smi")
    monkeypatch.setattr(hardware, "_run", lambda *a, **k: subprocess.CompletedProcess(a, 0, line, ""))
    [gpu] = hardware._nvidia_smi_gpus()
    assert gpu["vram_bus_width_bits"] == 512
    assert gpu["vram_data_rate_mts"] == 28002
    assert gpu["vram_bandwidth_gbps"] == pytest.approx(1792, abs=1)


# --- decode estimate built on that bandwidth -------------------------------

from lcc_core import estimates  # noqa: E402

RTX5090 = {"cpu": {"logical_cores": 24},
           "primary_gpu": {"name": "NVIDIA GeForce RTX 5090", "vram_bandwidth_gbps": 1792.1}}
FULL_GPU = {"gpu_layers": 999, "ctx_size": 131072, "flash_attn": True}


def test_dense_estimate_brackets_the_measured_rate(monkeypatch):
    # Qwen3.8-27B UD-Q5_K_XL, 20.9 GB, measured 51.6-59.7 t/s through LCC.
    monkeypatch.setattr(estimates, "_moe_active_fraction", lambda model: None)
    model = {"name": "Qwen3.8-27B-GGUF", "params_b": 27.0, "quant": "Q5_K_XL", "size_bytes": 20876938144}
    est = estimates.estimate_tokens_per_second(FULL_GPU, model, RTX5090)
    assert est["low_tps"] <= 52 and est["high_tps"] >= 60
    assert 50 <= est["estimate_tps"] <= 62
    assert est["confidence"] == "high"


def test_moe_reads_only_its_active_share_and_says_so(monkeypatch):
    monkeypatch.setattr(estimates, "_moe_active_fraction", lambda model: 0.12)
    model = {"name": "Ornith-35B-A3B", "params_b": 35.0, "quant": "Q4_K_XL", "size_bytes": 24 * 1024**3}
    moe = estimates.estimate_tokens_per_second(FULL_GPU, model, RTX5090)
    monkeypatch.setattr(estimates, "_moe_active_fraction", lambda model: None)
    dense = estimates.estimate_tokens_per_second(FULL_GPU, model, RTX5090)
    assert moe["estimate_tps"] > 3 * dense["estimate_tps"]
    assert moe["confidence"] == "medium"
    assert any("mixture-of-experts" in a.lower() for a in moe["assumptions"])


def test_active_fraction_prefers_the_name_over_expert_counts():
    # "A3B" on a 35B model: 3/35 of the weights per token.
    assert estimates._active_fraction_from_name("Ornith-1.5-35B-A3B-GGUF", 35.0) == pytest.approx(3 / 35)
    assert estimates._active_fraction_from_name("Qwen3.8-27B-GGUF", 27.0) is None
