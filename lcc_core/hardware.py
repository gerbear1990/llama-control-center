from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
from typing import Any

from .paths import is_windows


def _run(args: list[str], timeout: float = 2.0) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _detect_ram_speed() -> dict[str, Any] | None:
    """Detect RAM speed, type, and bandwidth where available."""
    if is_windows():
        return _windows_ram_speed()
    elif platform.system() == "Darwin":
        return _mac_ram_speed()
    else:
        return _linux_ram_speed()


def _windows_ram_speed() -> dict[str, Any] | None:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return None
    command = (
        "$mem = @(Get-CimInstance Win32_PhysicalMemory); "
        "if ($mem.Count -eq 0) { exit 0 }; "
        "[pscustomobject]@{"
        "Speed = ($mem | Select-Object -First 1).Speed; "
        "Type = ($mem | Select-Object -First 1).MemoryType; "
        "Manufacturer = ($mem | Select-Object -First 1).Manufacturer; "
        "ConfiguredSpeed = ($mem | Select-Object -First 1).ConfiguredClockSpeed; "
        "} | ConvertTo-Json -Compress"
    )
    result = _run([powershell, "-NoProfile", "-Command", command], timeout=3.0)
    if not result or result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    speed = _int_or_none(payload.get("Speed")) or _int_or_none(payload.get("ConfiguredSpeed"))
    mem_type = payload.get("Type")
    ram_type = _windows_memory_type(mem_type)
    return {
        "speed_mts": speed,
        "type": ram_type,
        "bandwidth_gbps": _calculate_ram_bandwidth(speed, ram_type),
    }


def _windows_memory_type(mem_type_code: Any) -> str | None:
    if mem_type_code is None:
        return None
    try:
        code = int(mem_type_code)
        type_map = {
            20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 30: "DDR5",
        }
        return type_map.get(code, f"RAM-{code}")
    except (ValueError, TypeError):
        return None


def _mac_ram_speed() -> dict[str, Any] | None:
    profiler = shutil.which("system_profiler")
    if not profiler:
        return None
    result = _run([profiler, "SPMemoryDataType", "-json"], timeout=4.0)
    if not result or result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    memory_modules = payload.get("SPMemoryDataType") or []
    if not memory_modules:
        return None
    speed_str = memory_modules[0].get("SPMemorySpeedKey", "") if isinstance(memory_modules[0], dict) else ""
    speed = None
    ram_type = None
    if isinstance(speed_str, str):
        match = re.search(r"(\d+)", speed_str)
        if match:
            speed = int(match.group(1))
        if "DDR4" in speed_str:
            ram_type = "DDR4"
        elif "DDR5" in speed_str:
            ram_type = "DDR5"
        elif "LPDDR" in speed_str:
            ram_type = "LPDDR"
    return {
        "speed_mts": speed,
        "type": ram_type,
        "bandwidth_gbps": _calculate_ram_bandwidth(speed, ram_type),
    }


def _linux_ram_speed() -> dict[str, Any] | None:
    dmidecode = shutil.which("dmidecode")
    if not dmidecode:
        return None
    result = _run([dmidecode, "-t", "memory"], timeout=3.0)
    if not result or result.returncode != 0:
        return None
    speed = None
    ram_type = None
    for line in result.stdout.splitlines():
        line_lower = line.lower().strip()
        if "speed" in line_lower and "unknown" not in line_lower:
            match = re.search(r"(\d+)\s*MT/s", line)
            if match:
                speed = int(match.group(1))
        if "type" in line_lower and "unknown" not in line_lower and "error" not in line_lower:
            for t in ["DDR", "DDR2", "DDR3", "DDR4", "DDR5"]:
                if t.lower() in line_lower:
                    ram_type = t
                    break
    if speed:
        return {
            "speed_mts": speed,
            "type": ram_type,
            "bandwidth_gbps": _calculate_ram_bandwidth(speed, ram_type),
        }
    return None


def _calculate_ram_bandwidth(speed_mts: int | None, ram_type: str | None) -> float | None:
    if not speed_mts or speed_mts <= 0:
        return None
    if ram_type in ("DDR", "DDR2", "DDR3"):
        return round(speed_mts * 8 / 1000, 1)
    if ram_type == "DDR4":
        return round(speed_mts * 8 / 1000, 1)
    if ram_type == "DDR5":
        return round(speed_mts * 16 / 1000, 1)
    if ram_type and "LPDDR" in ram_type:
        return round(speed_mts * 16 / 1000, 1)
    return round(speed_mts * 8 / 1000, 1)


def _windows_memory_info() -> dict[str, int | None]:
    if not is_windows():
        return {"total_bytes": None, "available_bytes": None}

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {
            "total_bytes": int(status.ullTotalPhys),
            "available_bytes": int(status.ullAvailPhys),
        }
    return {"total_bytes": None, "available_bytes": None}


def _posix_memory_info() -> dict[str, int | None]:
    if is_windows():
        return {"total_bytes": None, "available_bytes": None}
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        total = int(pages) * int(page_size)
        available = None
        if hasattr(os, "sysconf_names") and "SC_AVPHYS_PAGES" in os.sysconf_names:
            available = int(os.sysconf("SC_AVPHYS_PAGES")) * int(page_size)
        return {"total_bytes": total, "available_bytes": available}
    except (AttributeError, OSError, ValueError):
        return {"total_bytes": None, "available_bytes": None}


def detect_memory() -> dict[str, Any]:
    memory = _windows_memory_info() if is_windows() else _posix_memory_info()
    if platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}:
        memory["unified"] = True
    else:
        memory["unified"] = False
    
    ram_speed = _detect_ram_speed()
    if ram_speed:
        memory["ram_speed_mts"] = ram_speed.get("speed_mts")
        memory["ram_bandwidth_gbps"] = ram_speed.get("bandwidth_gbps")
        memory["ram_type"] = ram_speed.get("type")
    else:
        memory["ram_type"] = None
        memory["ram_bandwidth_gbps"] = None
    
    return memory


def _windows_cpu_info() -> dict[str, Any]:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return {}
    command = (
        "$cpus = @(Get-CimInstance Win32_Processor); "
        "[pscustomobject]@{"
        "Name = ($cpus | Select-Object -First 1).Name; "
        "Physical = ($cpus | Measure-Object -Property NumberOfCores -Sum).Sum; "
        "Logical = ($cpus | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum"
        "} | ConvertTo-Json -Compress"
    )
    result = _run([powershell, "-NoProfile", "-Command", command], timeout=3.0)
    if not result or result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return {
        "name": payload.get("Name"),
        "physical_cores": _int_or_none(payload.get("Physical")),
        "logical_cores": _int_or_none(payload.get("Logical")),
    }


def detect_cpu() -> dict[str, Any]:
    cpu = _windows_cpu_info() if is_windows() else {}
    if platform.system() == "Darwin":
        sysctl = shutil.which("sysctl")
        if sysctl:
            result = _run([sysctl, "-n", "machdep.cpu.brand_string"], timeout=1.5)
            if result and result.returncode == 0 and result.stdout.strip():
                cpu["name"] = result.stdout.strip()
    logical = cpu.get("logical_cores") or os.cpu_count()
    name = cpu.get("name") or platform.processor() or platform.machine() or "Unknown CPU"
    return {
        "name": str(name).strip(),
        "physical_cores": cpu.get("physical_cores"),
        "logical_cores": logical,
        "architecture": platform.machine(),
    }


def _nvidia_smi_gpus() -> list[dict[str, Any]]:
    binary = shutil.which("nvidia-smi") or shutil.which("nvidia-smi.exe")
    if not binary:
        return []
    result = _run(
        [
            binary,
            "--query-gpu=index,name,memory.total,memory.free,driver_version,memory.bus_width,memory.data_rate",
            "--format=csv,noheader,nounits",
        ],
        timeout=2.5,
    )
    if not result or result.returncode != 0:
        return []

    gpus: list[dict[str, Any]] = []
    for raw_line in result.stdout.splitlines():
        parts = [part.strip() for part in raw_line.split(",")]
        if len(parts) < 5:
            continue
        total_mib = _int_or_none(parts[2])
        free_mib = _int_or_none(parts[3])
        bus_width = _int_or_none(parts[5]) if len(parts) > 5 else None
        data_rate = _int_or_none(parts[6]) if len(parts) > 6 else None
        vram_bandwidth_gbps = None
        if bus_width and data_rate and data_rate > 0:
            vram_bandwidth_gbps = round(bus_width * data_rate / 1000, 1)
        gpus.append(
            {
                "index": _int_or_none(parts[0]),
                "name": parts[1],
                "vram_total_bytes": total_mib * 1024 * 1024 if total_mib is not None else None,
                "vram_free_bytes": free_mib * 1024 * 1024 if free_mib is not None else None,
                "vram_bus_width_bits": bus_width,
                "vram_data_rate_mts": data_rate,
                "vram_bandwidth_gbps": vram_bandwidth_gbps,
                "driver_version": parts[4],
                "backend": "nvidia-smi",
                "vendor": "NVIDIA",
                "integrated": False,
                "acceleration_backend": "cuda",
                "acceleration_options": ["cuda", "vulkan", "cpu"],
            }
        )
    return gpus


def _gpu_vendor(name: str) -> str | None:
    lowered = name.lower()
    if "nvidia" in lowered or "geforce" in lowered or "quadro" in lowered or "rtx" in lowered:
        return "NVIDIA"
    if "amd" in lowered or "radeon" in lowered or "firepro" in lowered:
        return "AMD"
    if "intel" in lowered or "arc" in lowered or "iris" in lowered or "uhd" in lowered:
        return "Intel"
    if "apple" in lowered or "m1" in lowered or "m2" in lowered or "m3" in lowered or "m4" in lowered:
        return "Apple"
    return None


def _gpu_integrated(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ["uhd", "iris", "vega", "integrated", "apple", "apu"])


def _acceleration_options(vendor: str | None, system: str | None = None) -> list[str]:
    system = system or platform.system()
    if system == "Darwin":
        return ["metal", "cpu"]
    if vendor == "NVIDIA":
        return ["cuda", "vulkan", "cpu"]
    if vendor == "AMD":
        return ["vulkan", "hip", "cpu"]
    if vendor == "Intel":
        return ["vulkan", "sycl", "cpu"]
    return ["cpu"]


def _preferred_backend(vendor: str | None, system: str | None = None) -> str:
    options = _acceleration_options(vendor, system)
    return options[0] if options else "cpu"


def _is_virtual_display(name: str) -> bool:
    lowered = name.lower()
    virtual_markers = [
        "virtual",
        "remote",
        "parsec",
        "mirage",
        "basic display",
        "meta virtual monitor",
        "spacedesk",
    ]
    return any(marker in lowered for marker in virtual_markers)


def _windows_display_gpus() -> list[dict[str, Any]]:
    if not is_windows():
        return []
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return []
    command = (
        "$gpus = Get-CimInstance Win32_VideoController | "
        "Where-Object { $_.Name -match 'NVIDIA|AMD|Radeon|Intel|Arc|Iris|UHD' } | "
        "Select-Object Name,AdapterRAM,DriverVersion,VideoProcessor,PNPDeviceID; "
        "$gpus | ConvertTo-Json -Compress"
    )
    result = _run([powershell, "-NoProfile", "-Command", command], timeout=3.0)
    if not result or result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    items = payload if isinstance(payload, list) else [payload]
    gpus: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or item.get("VideoProcessor") or "Display adapter").strip()
        if not name or _is_virtual_display(name):
            continue
        vendor = _gpu_vendor(name)
        adapter_ram = _int_or_none(item.get("AdapterRAM"))
        gpus.append(
            {
                "index": idx,
                "name": name,
                "vram_total_bytes": adapter_ram if adapter_ram and adapter_ram > 0 else None,
                "vram_free_bytes": None,
                "driver_version": item.get("DriverVersion"),
                "backend": "windows-cim",
                "vendor": vendor,
                "integrated": _gpu_integrated(name),
                "acceleration_backend": _preferred_backend(vendor),
                "acceleration_options": _acceleration_options(vendor),
            }
        )
    return gpus


def _mac_display_gpus() -> list[dict[str, Any]]:
    if platform.system() != "Darwin":
        return []
    profiler = shutil.which("system_profiler")
    if not profiler:
        return []
    result = _run([profiler, "SPDisplaysDataType", "-json"], timeout=4.0)
    if not result or result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    items = payload.get("SPDisplaysDataType") or []
    gpus: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = item.get("sppci_model") or item.get("_name") or item.get("spdisplays_vendor") or "Apple GPU"
        vendor = _gpu_vendor(str(name)) or "Apple"
        vram_text = " ".join(
            str(item.get(key, "")) for key in ["spdisplays_vram", "spdisplays_vram_shared", "spdisplays_vram_dynamic"]
        )
        vram_bytes = None
        match = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB)", vram_text, flags=re.IGNORECASE)
        if match:
            value = float(match.group(1))
            unit = match.group(2).lower()
            vram_bytes = int(value * (1024**3 if unit == "gb" else 1024**2))
        gpus.append(
            {
                "index": idx,
                "name": str(name),
                "vram_total_bytes": vram_bytes,
                "vram_free_bytes": None,
                "driver_version": None,
                "backend": "system-profiler",
                "vendor": vendor,
                "integrated": True,
                "unified_memory": True,
                "acceleration_backend": "metal",
                "acceleration_options": ["metal", "cpu"],
            }
        )
    return gpus


def _linux_lspci_gpus() -> list[dict[str, Any]]:
    if platform.system() == "Darwin" or is_windows():
        return []
    lspci = shutil.which("lspci")
    if not lspci:
        return []
    result = _run([lspci], timeout=2.0)
    if not result or result.returncode != 0:
        return []
    gpus: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if not re.search(r"(?i)(vga|3d controller|display controller)", line):
            continue
        name = re.sub(r"^[0-9a-fA-F:.]+\s+", "", line).strip()
        if _is_virtual_display(name):
            continue
        vendor = _gpu_vendor(name)
        gpus.append(
            {
                "index": len(gpus),
                "name": name,
                "vram_total_bytes": None,
                "vram_free_bytes": None,
                "driver_version": None,
                "backend": "lspci",
                "vendor": vendor,
                "integrated": _gpu_integrated(name),
                "acceleration_backend": _preferred_backend(vendor, platform.system()),
                "acceleration_options": _acceleration_options(vendor, platform.system()),
            }
        )
    return gpus


def _dedupe_gpus(gpus: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for gpu in gpus:
        name = str(gpu.get("name") or "").lower()
        vendor = str(gpu.get("vendor") or "").lower()
        key = re.sub(r"[^a-z0-9]+", "", f"{vendor}:{name}")
        if not key or key in seen:
            continue
        seen.add(key)
        gpu["index"] = len(deduped)
        deduped.append(gpu)
    return deduped


def detect_gpus() -> list[dict[str, Any]]:
    gpus = _nvidia_smi_gpus()
    if is_windows():
        gpus.extend(_windows_display_gpus())
    elif platform.system() == "Darwin":
        gpus.extend(_mac_display_gpus())
    else:
        gpus.extend(_linux_lspci_gpus())
    return _dedupe_gpus(gpus)


def recommended_headroom_mib(gpus: list[dict[str, Any]]) -> int:
    primary = next((gpu for gpu in gpus if gpu.get("vram_total_bytes")), None)
    if not primary:
        return 1024
    total_mib = int(primary["vram_total_bytes"] / 1024 / 1024)
    return max(1024, min(4096, int(round(total_mib * 0.06 / 256) * 256)))


def detect_system_hardware() -> dict[str, Any]:
    gpus = detect_gpus()
    memory = detect_memory()
    primary_gpu = gpus[0] if gpus else None
    warnings: list[str] = []
    if not gpus:
        warnings.append("No GPU was detected. NVIDIA VRAM details require nvidia-smi; AMD/Intel fallback uses OS display APIs.")
    if memory.get("total_bytes") is None:
        warnings.append("System memory size could not be detected on this platform.")

    return {
        "cpu": detect_cpu(),
        "memory": memory,
        "gpus": gpus,
        "primary_gpu": primary_gpu,
        "recommended_fit_target_mib": recommended_headroom_mib(gpus),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
        },
        "warnings": warnings,
    }
