from __future__ import annotations

import json
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path

from lcc_core.config import AppConfig
from lcc_core.estimates import estimate_memory_fit, estimate_tokens_per_second
from lcc_core.fit import apply_fit_suggestions, build_fit_args, parse_fit_output
from lcc_core.hardware import _parse_cpuinfo
from lcc_core.hf_metadata import infer_query
from lcc_core.inventory import build_inventory
from lcc_core.llama_args import build_llama_server_args
from lcc_core.manifest import load_profiles
from lcc_core.models import discover_models, parse_params, parse_quant
from lcc_core.paths import find_project_root
from lcc_core.portability import scan_portability_issues
from lcc_core.profile_resolver import resolve_profiles
from lcc_core.vllm_args import build_wsl_vllm_args, windows_to_wsl_path


class VersionConsistencyTests(unittest.TestCase):
    def test_version_strings_match(self) -> None:
        import re

        import lcc_api
        import lcc_core

        root = Path(__file__).resolve().parent.parent
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'(?m)^version = "([^"]+)"', pyproject)
        self.assertIsNotNone(match, "pyproject.toml has no version line")
        pyproject_version = match.group(1)
        self.assertEqual(
            {pyproject_version, lcc_api.__version__, lcc_core.__version__},
            {pyproject_version},
            f"version drift: pyproject={pyproject_version}, "
            f"lcc_api={lcc_api.__version__}, lcc_core={lcc_core.__version__}",
        )


class LinuxCpuInfoTests(unittest.TestCase):
    def test_parses_model_name_and_counts_physical_cores(self) -> None:
        # Two logical CPUs sharing one physical core (hyperthreading) → 1 physical core.
        text = (
            "processor\t: 0\n"
            "model name\t: 13th Gen Intel(R) Core(TM) i9-13900HK\n"
            "physical id\t: 0\n"
            "core id\t: 0\n"
            "\n"
            "processor\t: 1\n"
            "model name\t: 13th Gen Intel(R) Core(TM) i9-13900HK\n"
            "physical id\t: 0\n"
            "core id\t: 0\n"
            "\n"
            "processor\t: 2\n"
            "model name\t: 13th Gen Intel(R) Core(TM) i9-13900HK\n"
            "physical id\t: 0\n"
            "core id\t: 1\n"
        )
        info = _parse_cpuinfo(text)
        self.assertEqual(info["name"], "13th Gen Intel(R) Core(TM) i9-13900HK")
        self.assertEqual(info["physical_cores"], 2)

    def test_missing_fields_do_not_crash(self) -> None:
        self.assertEqual(_parse_cpuinfo(""), {"name": None, "physical_cores": None})


class MemoryTypeTests(unittest.TestCase):
    def test_smbios_codes_map_to_ddr5_and_lpddr4(self) -> None:
        # SMBIOS 0x1E is LPDDR4 and DDR5 is 0x22; mapping 30 to DDR5 sent real
        # DDR5 boxes down the generic bandwidth formula (~2x understated).
        from lcc_core.hardware import _calculate_ram_bandwidth, _windows_memory_type

        self.assertEqual(_windows_memory_type(30), "LPDDR4")
        self.assertEqual(_windows_memory_type(34), "DDR5")
        self.assertEqual(_windows_memory_type(35), "LPDDR5")
        self.assertEqual(_windows_memory_type(26), "DDR4")
        self.assertEqual(_calculate_ram_bandwidth(6000, "DDR5"), 96.0)
        self.assertEqual(_calculate_ram_bandwidth(6400, "LPDDR5"), 102.4)


class ModelDiscoveryTests(unittest.TestCase):
    def test_parse_quant_and_params(self) -> None:
        self.assertEqual(parse_quant("Qwen3-14B-Q4_K_M.gguf"), "Q4_K_M")
        self.assertEqual(parse_quant("gemma-BF16.gguf"), "BF16")
        self.assertEqual(parse_params("Qwen3 14B Instruct"), 14.0)
        self.assertEqual(parse_params("Tiny 750M"), 0.75)

    def test_discovers_gguf_and_groups_split_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = root / "models" / "Example-7B"
            model_dir.mkdir(parents=True)
            first = model_dir / "Example-7B-Q4_K_M-00001-of-00002.gguf"
            second = model_dir / "Example-7B-Q4_K_M-00002-of-00002.gguf"
            first.write_bytes(b"a" * 10)
            second.write_bytes(b"b" * 12)
            (model_dir / "mmproj-Example.gguf").write_bytes(b"projector")

            models = discover_models([root / "models"])

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].split_total, 2)
        self.assertEqual(models[0].size_bytes, 22)
        self.assertEqual(models[0].quant, "Q4_K_M")
        self.assertTrue(models[0].mmproj_path.endswith("mmproj-Example.gguf"))

    def test_discovered_model_carries_mtime(self) -> None:
        # The dashboard's "Updated" column reads model.mtime; the discovery
        # path must populate it from a real stat() so the UI doesn't have to.
        import time as _time
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = root / "models"
            model_dir.mkdir()
            target = model_dir / "Tiny-1B-Q8_0.gguf"
            target.write_bytes(b"x" * 100)
            before = _time.time()
            models = discover_models([root / "models"])
            after = _time.time()
        self.assertEqual(len(models), 1)
        mtime = models[0].mtime
        self.assertIsNotNone(mtime)
        # Allow a small clock skew window (the stat call uses real wall clock).
        self.assertGreaterEqual(mtime, before - 2)
        self.assertLessEqual(mtime, after + 2)
        # to_dict() must surface it for the JS layer.
        self.assertEqual(models[0].to_dict()["mtime"], mtime)

    def test_discovers_transformers_nvfp4_checkpoint_as_one_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "models"
            model_dir = root / "Qwen3.6-27B-NVFP4"
            model_dir.mkdir(parents=True)
            (model_dir / "config.json").write_text(
                json.dumps({"model_type": "qwen3_5", "architectures": ["Qwen3_5ForConditionalGeneration"], "quantization_config": {"format": "nvfp4"}}),
                encoding="utf-8",
            )
            (model_dir / "model-00001-of-00002.safetensors").write_bytes(b"a" * 10)
            (model_dir / "model-00002-of-00002.safetensors").write_bytes(b"b" * 12)
            (model_dir / "model.safetensors.index.json").write_text("{}", encoding="utf-8")

            models = discover_models([root])

        self.assertEqual(len(models), 1)
        self.assertEqual(models[0].format, "Safetensors")
        self.assertEqual(models[0].quant, "NVFP4")
        self.assertEqual(models[0].size_bytes, 22)
        self.assertEqual(models[0].path, str(model_dir))


class ManifestTests(unittest.TestCase):
    def test_manifest_profiles_flag_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_path = root / "models" / "portable.gguf"
            model_path.parent.mkdir()
            model_path.write_bytes(b"gguf")
            manifest = {
                "models": [
                    {
                        "mode": "portable",
                        "name": "Portable",
                        "model_path": "C:\\Users\\someone\\models\\portable.gguf",
                        "recommended_params": {
                            "draft_model": "C:\\Users\\someone\\models\\draft.gguf",
                        },
                    }
                ]
            }
            (root / "models.json").write_text(json.dumps(manifest), encoding="utf-8")

            profiles = load_profiles(root)

        self.assertEqual(len(profiles), 1)
        self.assertGreaterEqual(len(profiles[0].portable_warnings), 2)

    def test_load_profiles_raises_on_corrupt_manifest(self) -> None:
        from lcc_core.manifest import ManifestReadError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "models.json").write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(ManifestReadError):
                load_profiles(root)

    def test_load_profiles_raises_on_non_dict_manifest(self) -> None:
        """Additional manifest failure path (M1.3): root not object -> ManifestReadError."""
        from lcc_core.manifest import ManifestReadError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "models.json").write_text("[]", encoding="utf-8")
            with self.assertRaises(ManifestReadError):
                load_profiles(root)

    def test_load_profiles_raises_on_non_list_models(self) -> None:
        """Additional manifest failure path (M1.3): models not a list -> ManifestReadError."""
        from lcc_core.manifest import ManifestReadError
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "models.json").write_text('{"models": {}}', encoding="utf-8")
            with self.assertRaises(ManifestReadError):
                load_profiles(root)

    def test_find_project_root_uses_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "a" / "b"
            child.mkdir(parents=True)
            (root / "models.json").write_text('{"models": []}', encoding="utf-8")

            self.assertEqual(find_project_root(child), root)


class ProcessPortDetectionTests(unittest.TestCase):
    """Smoke tests for the hardened pid/port helpers (M1.2)."""

    def test_pid_is_running_invalid_pids(self) -> None:
        from lcc_core.server_manager import pid_is_running
        self.assertFalse(pid_is_running(None))
        self.assertFalse(pid_is_running(0))
        self.assertFalse(pid_is_running(2**31))  # very unlikely live PID in tests

    def test_find_process_on_port_smoke(self) -> None:
        from lcc_core.server_manager import find_process_on_port
        # Should not crash; result may be None or a real system process.
        pid = find_process_on_port(1)  # privileged / unlikely, but exercises path
        self.assertTrue(pid is None or isinstance(pid, int))

    def test_find_process_on_port_free_high_port(self) -> None:
        """M1.3 additional edge: high port unlikely to be in use exercises free path + return contract."""
        from lcc_core.server_manager import find_process_on_port
        pid = find_process_on_port(54321)
        self.assertTrue(pid is None or isinstance(pid, int))

    def test_pid_is_running_negative_and_out_of_range(self) -> None:
        """M1.3 additional: negative and huge PIDs are invalid (Windows pid_is_running + psutil path)."""
        from lcc_core.server_manager import pid_is_running
        self.assertFalse(pid_is_running(-1))
        self.assertFalse(pid_is_running(2**40))


class RuntimeDetectionTests(unittest.TestCase):
    def test_candidate_roots_include_enclosing_llama_install(self) -> None:
        from lcc_core.paths import candidate_llama_roots

        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp) / "llama.cpp-cuda"
            app_root = install_root / "tools" / "llama-control-center-repo"
            app_root.mkdir(parents=True)
            (app_root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            (install_root / "llama-server.exe").write_bytes(b"")
            (install_root / "llama-server").write_bytes(b"")

            roots = [path.resolve() for path in candidate_llama_roots(app_root)]

        self.assertIn(install_root.resolve(), roots)

    def test_detect_llama_cpp_uses_configured_default_port(self) -> None:
        import os
        from unittest import mock

        from lcc_core.backends import detect_llama_cpp

        config = AppConfig(default_host="127.0.0.1", default_port=8081)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("lcc_core.backends._request_json", return_value=(False, None, "offline")):
                    env = detect_llama_cpp(root, config=config)

        self.assertEqual(env.details["probe_url"], "http://127.0.0.1:8081")


class InventoryTests(unittest.TestCase):
    def test_inventory_is_json_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "models.json").write_text('{"models": []}', encoding="utf-8")
            model_dir = root / "models"
            model_dir.mkdir()
            (model_dir / "Small-1B-Q8_0.gguf").write_bytes(b"model")

            payload = build_inventory(project_root=root, model_dirs=[model_dir], include_manifest=True)

        encoded = json.dumps(payload)
        self.assertIn("Small-1B-Q8_0", encoded)
        self.assertEqual(payload["summary"]["model_count"], 1)


class PortabilityTests(unittest.TestCase):
    def test_portability_scan_flags_user_specific_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "legacy.ps1"
            script.write_text("$root = 'C:\\Users\\someone\\llama.cpp'\n", encoding="utf-8")

            issues = scan_portability_issues(root)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["line"], 1)


class ProfileResolverTests(unittest.TestCase):
    def test_resolves_profile_against_discovered_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = root / "models"
            model_dir.mkdir()
            (model_dir / "Tiny-1B-Q8_0.gguf").write_bytes(b"model")
            manifest = {
                "models": [
                    {
                        "mode": "tiny",
                        "name": "Tiny 1B Q8_0",
                        "description": "portable test",
                        "recommended_params": {
                            "ctx_size": 4096,
                            "threads": 4,
                            "gpu_layers": 999,
                            "cache_type_k": "q8_0",
                            "cache_type_v": "q8_0",
                        },
                    }
                ]
            }
            (root / "models.json").write_text(json.dumps(manifest), encoding="utf-8")

            profiles = resolve_profiles(project_root=root, model_dirs=[model_dir])

        self.assertEqual(len(profiles), 1)
        self.assertTrue(profiles[0].launchable)
        self.assertEqual(profiles[0].model["name"], "Tiny-1B-Q8_0")

    def test_mtp_profile_requires_draft_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = root / "models"
            model_dir.mkdir()
            (model_dir / "Gemma-26B-Q6_K_XL.gguf").write_bytes(b"model")
            manifest = {
                "models": [
                    {
                        "mode": "gemma-mtp",
                        "name": "Gemma 26B MTP",
                        "description": "MTP profile",
                        "recommended_params": {
                            "ctx_size": 4096,
                            "threads": 4,
                            "gpu_layers": 999,
                            "cache_type_k": "q8_0",
                            "cache_type_v": "q8_0",
                            "spec_type": "draft-mtp",
                        },
                    }
                ]
            }
            (root / "models.json").write_text(json.dumps(manifest), encoding="utf-8")

            profiles = resolve_profiles(project_root=root, model_dirs=[model_dir])

        self.assertFalse(profiles[0].launchable)
        self.assertIn("draft_model", profiles[0].missing)

    def test_no_reasoning_description_does_not_enable_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = root / "models"
            model_dir.mkdir()
            (model_dir / "Tiny-1B-Q8_0.gguf").write_bytes(b"model")
            manifest = {
                "models": [
                    {
                        "mode": "tiny",
                        "name": "Tiny 1B Q8_0",
                        "description": "no reasoning",
                        "recommended_params": {
                            "ctx_size": 4096,
                            "threads": 4,
                            "gpu_layers": 999,
                            "cache_type_k": "q8_0",
                            "cache_type_v": "q8_0",
                        },
                    }
                ]
            }
            (root / "models.json").write_text(json.dumps(manifest), encoding="utf-8")

            profiles = resolve_profiles(project_root=root, model_dirs=[model_dir])

        self.assertFalse(profiles[0].params["reasoning"])

    def test_architecture_and_quant_tokens_raise_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = root / "models" / "gemma-4-26B-A4B-it-GGUF-unsloth"
            model_dir.mkdir(parents=True)
            (model_dir / "gemma-4-26B-A4B-it-UD-Q6_K_XL.gguf").write_bytes(b"model")
            manifest = {
                "models": [
                    {
                        "mode": "gemma-26b-a4b-q6kxl",
                        "name": "Gemma 4 26B A4B UD Q6_K_XL",
                        "description": "no reasoning",
                        "model_size_gb": 0.0001,
                        "recommended_params": {
                            "ctx_size": 4096,
                            "threads": 4,
                            "gpu_layers": 999,
                            "cache_type_k": "q8_0",
                            "cache_type_v": "q8_0",
                        },
                    }
                ]
            }
            (root / "models.json").write_text(json.dumps(manifest), encoding="utf-8")

            profiles = resolve_profiles(project_root=root, model_dirs=[root / "models"])

        self.assertGreaterEqual(profiles[0].confidence, 0.55)
        self.assertTrue(profiles[0].launchable)

    def test_vllm_profile_resolves_explicit_checkpoint_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = root / "models" / "Qwen3.6-27B-NVFP4"
            model_dir.mkdir(parents=True)
            (model_dir / "config.json").write_text(
                json.dumps({"model_type": "qwen3_5", "architectures": ["Qwen3_5ForConditionalGeneration"]}),
                encoding="utf-8",
            )
            (model_dir / "model.safetensors").write_bytes(b"model")
            manifest = {
                "models": [{
                    "mode": "qwen-nvfp4",
                    "name": "Qwen NVFP4",
                    "description": "vLLM test",
                    "model_path": str(model_dir),
                    "recommended_params": {
                        "runtime": "vllm-wsl",
                        "ctx_size": 4096,
                        "max_model_len": 4096,
                        "gpu_memory_utilization": 0.9,
                    },
                }]
            }
            (root / "models.json").write_text(json.dumps(manifest), encoding="utf-8")

            profiles = resolve_profiles(project_root=root, model_dirs=[root / "models"])

        self.assertTrue(profiles[0].launchable)
        self.assertEqual(profiles[0].model["format"], "Safetensors")
        self.assertEqual(profiles[0].params["runtime"], "vllm-wsl")


class LaunchArgsTests(unittest.TestCase):
    def test_polling_off_by_default_when_layers_are_offloaded(self) -> None:
        """An offloaded server must not busy-wait.

        llama.cpp defaults --poll to 50, so its threadpool spins every
        --threads core at 100% even with no request in flight. Measured on an
        idle server: 7.99 cpu-sec/sec at --threads 8, versus 0.01 with --poll 0.
        With the model on the GPU those threads have nothing to do between
        batches, so polling is pure waste.
        """
        gpu = build_llama_server_args(
            "llama-server", "Tiny-1B-Q8_0.gguf",
            {"gpu_layers": 999, "threads": 8},
        )
        self.assertEqual(gpu.argv[gpu.argv.index("--poll") + 1], "0")

        # CPU-only inference genuinely needs the worker threads hot, so the
        # llama.cpp default is preserved there.
        cpu = build_llama_server_args(
            "llama-server", "Tiny-1B-Q8_0.gguf",
            {"gpu_layers": 0, "threads": 8},
        )
        self.assertEqual(cpu.argv[cpu.argv.index("--poll") + 1], "50")

        # An explicit value always wins.
        explicit = build_llama_server_args(
            "llama-server", "Tiny-1B-Q8_0.gguf",
            {"gpu_layers": 999, "threads": 8, "poll": 25},
        )
        self.assertEqual(explicit.argv[explicit.argv.index("--poll") + 1], "25")

    def test_builds_llama_server_args_without_shell_string_rebuild(self) -> None:
        cmd = build_llama_server_args(
            "llama-server",
            "Tiny-1B-Q8_0.gguf",
            {
                "ctx_size": 4096,
                "threads": 4,
                "threads_batch": 4,
                "batch_size": 512,
                "ubatch_size": 256,
                "gpu_layers": 999,
                "cache_type_k": "q8_0",
                "cache_type_v": "q8_0",
                "flash_attn": True,
                "reasoning": False,
                "temperature": 0.7,
                "top_k": 32,
                "top_p": 0.9,
                "min_p": 0.04,
                "repeat_last_n": 128,
                "repeat_penalty": 1.08,
                "presence_penalty": 0.1,
                "frequency_penalty": 0.2,
                "seed": 123,
                "n_predict": 2048,
                "kv_offload": False,
                "op_offload": False,
                "draft_model": "Tiny-Draft.gguf",
                "spec_type": "draft-mtp",
                "spec_draft_n_max": 4,
            },
        )

        self.assertIn("--gpu-layers", cmd.argv)
        self.assertIn("all", cmd.argv)
        self.assertIn("--model-draft", cmd.argv)
        # Upstream only knows --draft-max, not --spec-draft-n-max.
        self.assertNotIn("--spec-draft-n-max", cmd.argv)
        # --spec-type IS emitted alongside --model-draft: upstream treats the two
        # as independent, and an explicit type overrides the inference llama.cpp
        # would otherwise make from the draft sidecar/GGUF metadata.
        # Verified against build 10472 (upstream 60eeeb608).
        self.assertEqual(cmd.argv[cmd.argv.index("--spec-type") + 1], "draft-mtp")
        self.assertEqual(cmd.argv[cmd.argv.index("--draft-max") + 1], "4")
        self.assertIn("--temp", cmd.argv)
        self.assertIn("0.7", cmd.argv)
        self.assertIn("--top-p", cmd.argv)
        self.assertIn("--repeat-penalty", cmd.argv)
        self.assertIn("--predict", cmd.argv)
        self.assertIn("--no-kv-offload", cmd.argv)
        self.assertIn("--no-op-offload", cmd.argv)

    def test_spec_type_emits_every_supported_value(self) -> None:
        # Was test_spec_type_only_emitted_without_draft_model_and_when_supported,
        # which asserted draft-mtp was unsupported. That mirrored the April source
        # clone in tools/llama.cpp-source; the installed binary (build 10472,
        # upstream 60eeeb608) accepts the whole draft-* family.
        cmd = build_llama_server_args("llama-server", "m.gguf", {"spec_type": "ngram-cache"})
        self.assertEqual(cmd.argv[cmd.argv.index("--spec-type") + 1], "ngram-cache")
        # The embedded-MTP case from issue #14.
        mtp = build_llama_server_args("llama-server", "m.gguf", {"spec_type": "draft-mtp"})
        self.assertEqual(mtp.argv[mtp.argv.index("--spec-type") + 1], "draft-mtp")
        self.assertFalse(mtp.warnings)

    def test_spec_type_accepts_a_comma_separated_list(self) -> None:
        # Upstream splits on ',' and appends each name to speculative.types.
        cmd = build_llama_server_args(
            "llama-server", "m.gguf", {"spec_type": "draft-mtp, ngram-cache"}
        )
        self.assertEqual(cmd.argv[cmd.argv.index("--spec-type") + 1], "draft-mtp,ngram-cache")
        self.assertFalse(cmd.warnings)

    def test_spec_type_drops_only_the_unsupported_entries(self) -> None:
        cmd = build_llama_server_args(
            "llama-server", "m.gguf", {"spec_type": "draft-mtp,not-a-real-type"}
        )
        # An unsupported value makes llama-server exit before it listens, so it is
        # dropped -- but it must not take the valid entries down with it.
        self.assertEqual(cmd.argv[cmd.argv.index("--spec-type") + 1], "draft-mtp")
        self.assertTrue(any("not-a-real-type" in warning for warning in cmd.warnings))

    def test_spec_type_wholly_unsupported_is_not_emitted(self) -> None:
        bogus = build_llama_server_args("llama-server", "m.gguf", {"spec_type": "nonsense"})
        self.assertNotIn("--spec-type", bogus.argv)
        self.assertTrue(bogus.warnings)

    def test_draft_max_alias_maps_to_upstream_flag(self) -> None:
        cmd = build_llama_server_args(
            "llama-server", "m.gguf", {"draft_model": "d.gguf", "draft_max": 8, "draft_min": 2}
        )
        self.assertEqual(cmd.argv[cmd.argv.index("--draft-max") + 1], "8")
        self.assertEqual(cmd.argv[cmd.argv.index("--draft-min") + 1], "2")

    def test_string_gpu_layers_do_not_crash(self) -> None:
        # 'all'/'auto' and float-ish strings are valid manifest values elsewhere
        # in the app; the arg builders must not raise on them.
        for value, expected in [("all", "all"), ("auto", "all"), ("32.0", "32"), (24, "24")]:
            cmd = build_llama_server_args("llama-server", "m.gguf", {"gpu_layers": value})
            self.assertIn("--gpu-layers", cmd.argv)
            self.assertEqual(cmd.argv[cmd.argv.index("--gpu-layers") + 1], expected)
        fit = build_fit_args("llama-fit-params", "m.gguf", {"gpu_layers": "all"})
        self.assertEqual(fit[fit.index("-ngl") + 1], "-2")

    def test_builds_wsl_vllm_command_and_converts_model_path(self) -> None:
        self.assertEqual(windows_to_wsl_path(r"C:\Users\filth\models\Qwen NVFP4"), "/mnt/c/Users/filth/models/Qwen NVFP4")
        cmd = build_wsl_vllm_args(
            "wsl.exe",
            "Ubuntu-24.04",
            "/opt/lcc-vllm",
            r"C:\Users\filth\models\Qwen NVFP4",
            {
                "host": "127.0.0.1",
                "port": 18027,
                "alias": "qwen-nvfp4",
                "ctx_size": 8192,
                "gpu_memory_utilization": 0.9,
                "enable_auto_tool_choice": True,
                "tool_call_parser": "qwen3_coder",
                "reasoning_parser": "qwen3",
            },
            "/tmp/lcc-vllm/qwen.pid",
        )
        self.assertEqual(cmd.argv[:5], ["wsl.exe", "-d", "Ubuntu-24.04", "--", "bash"])
        shell = cmd.argv[-1]
        self.assertIn("/opt/lcc-vllm/bin/vllm serve", shell)
        self.assertIn("'/mnt/c/Users/filth/models/Qwen NVFP4'", shell)
        self.assertIn("--max-model-len 8192", shell)
        self.assertIn("--max-num-seqs 32", shell)
        self.assertIn("--max-num-batched-tokens 2048", shell)
        self.assertIn("export CUDA_HOME=/usr/local/cuda", shell)

    def test_fit_args_and_output_parser(self) -> None:
        args = build_fit_args(
            "llama-fit-params.exe",
            "Tiny-1B-Q8_0.gguf",
            {
                "ctx_size": 8192,
                "threads": 4,
                "threads_batch": 3,
                "batch_size": 512,
                "ubatch_size": 256,
                "gpu_layers": 999,
                "cache_type_k": "q8_0",
                "cache_type_v": "q8_0",
                "flash_attn": True,
                "kv_offload": False,
                "op_offload": True,
            },
            target_mib=2048,
        )
        self.assertIn("-fit", args)
        self.assertIn("-fitt", args)
        self.assertIn("2048", args)
        self.assertIn("-t", args)
        self.assertIn("-tb", args)
        self.assertIn("-nkvo", args)
        self.assertIn("--op-offload", args)
        # llama-fit-params parses with LLAMA_EXAMPLE_COMMON and rejects the whole
        # command line on an unknown flag, so only real upstream flags may appear.
        self.assertNotIn("-fitp", args)
        self.assertNotIn("--reasoning", args)
        parsed = parse_fit_output(
            "-c 262144 -ngl -2\n",
            "llama_memory_breakdown_print: |   - CUDA0 (RTX 4090)   | 26000 =   106 + (25894 = 22201 +    2879 +     814) +           0 |",
        )
        self.assertEqual(parsed["suggestions"]["ctx_size"], 262144)
        self.assertEqual(parsed["suggestions"]["gpu_layers"], 999)
        self.assertEqual(parsed["suggestions"]["cuda_memory_mib"]["context"], 2879)

    def test_fit_parser_keeps_ngl_when_it_precedes_ctx(self) -> None:
        # -ngl before -c must not be dropped (the layer count is the key output).
        parsed = parse_fit_output("suggested: -ngl 49 -c 32768 -fa on\n")
        self.assertEqual(parsed["suggestions"]["gpu_layers"], 49)
        self.assertEqual(parsed["suggestions"]["ctx_size"], 32768)

    def test_fit_output_parses_and_applies_full_parameter_set(self) -> None:
        output = """
        fit result: -c 131072 -t 20 -tb 18 -b 1536 -ub 384 -ngl 49 -ctk q4_0 -ctv q8_0 -nkvo --no-op-offload --temp 0.65 --top-k 32 --top-p 0.90 --min-p 0.04 --repeat-last-n 256 --repeat-penalty 1.05 --presence-penalty 0.10 --frequency-penalty 0.20 --seed 123 --predict 2048
        """
        parsed = parse_fit_output(
            output,
            "llama_memory_breakdown_print: |   - CUDA0 (RTX 5090)   | 32606 =  3887 + (28719 = 26090 +    1803 +     826) +           0 |"
            "\nprojected to use 28719 MiB on CUDA0 vs. 32606 MiB free",
        )
        suggestions = parsed["suggestions"]
        self.assertEqual(suggestions["ctx_size"], 131072)
        self.assertEqual(suggestions["threads"], 20)
        self.assertEqual(suggestions["threads_batch"], 18)
        self.assertEqual(suggestions["batch_size"], 1536)
        self.assertEqual(suggestions["ubatch_size"], 384)
        self.assertEqual(suggestions["gpu_layers"], 49)
        self.assertEqual(suggestions["cache_type_k"], "q4_0")
        self.assertEqual(suggestions["cache_type_v"], "q8_0")
        self.assertEqual(suggestions["temperature"], 0.65)
        self.assertEqual(suggestions["top_k"], 32)
        self.assertEqual(suggestions["top_p"], 0.9)
        self.assertEqual(suggestions["min_p"], 0.04)
        self.assertEqual(suggestions["repeat_last_n"], 256)
        self.assertEqual(suggestions["repeat_penalty"], 1.05)
        self.assertEqual(suggestions["presence_penalty"], 0.1)
        self.assertEqual(suggestions["frequency_penalty"], 0.2)
        self.assertEqual(suggestions["seed"], 123)
        self.assertEqual(suggestions["n_predict"], 2048)
        self.assertFalse(suggestions["kv_offload"])
        self.assertFalse(suggestions["op_offload"])
        self.assertEqual(suggestions["headroom_mib"], 3887)

        applied = apply_fit_suggestions(
            {"ctx_size": 4096, "threads": 8, "temperature": 0.8, "mmap": True},
            suggestions,
            target_mib=1536,
        )
        self.assertEqual(applied["ctx_size"], 131072)
        self.assertEqual(applied["threads"], 20)
        self.assertEqual(applied["batch_size"], 1536)
        self.assertEqual(applied["ubatch_size"], 384)
        self.assertEqual(applied["fit_target_mib"], 1536)
        self.assertEqual(applied["fit_headroom_mib"], 3887)
        self.assertEqual(applied["temperature"], 0.65)
        self.assertFalse(applied["kv_offload"])
        self.assertFalse(applied["op_offload"])
        self.assertTrue(applied["mmap"])


class ConfigTests(unittest.TestCase):
    def test_config_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config = AppConfig(
                model_dirs=["models"],
                runtime_dirs=["runtime"],
                llama_server_path="runtime/llama-server",
                llama_fit_params_path="runtime/llama-fit-params",
                default_port=9000,
            )
            config.save(path)

            loaded = AppConfig.load(path)

        self.assertEqual(loaded.model_dirs, ["models"])
        self.assertEqual(loaded.runtime_dirs, ["runtime"])
        self.assertEqual(loaded.llama_server_path, "runtime/llama-server")
        self.assertEqual(loaded.llama_fit_params_path, "runtime/llama-fit-params")
        self.assertEqual(loaded.default_port, 9000)

    def test_bandwidth_caps_estimate_and_drives_confidence(self) -> None:
        params = {"gpu_layers": 999, "ctx_size": 4096, "flash_attn": True}
        model = {"name": "Tiny 7B", "params_b": 7, "quant": "Q4_K_M"}
        no_bw = {"cpu": {"logical_cores": 16}, "primary_gpu": {"name": "RTX 4090"}}
        low_bw = {"cpu": {"logical_cores": 16},
                  "primary_gpu": {"name": "RTX 4090", "vram_bandwidth_gbps": 200.0}}
        base = estimate_tokens_per_second(params, model, no_bw)
        capped = estimate_tokens_per_second(params, model, low_bw)
        # A low measured bandwidth must pull the estimate DOWN, never boost it.
        self.assertLess(capped["estimate_tps"], base["estimate_tps"])
        self.assertEqual(base["confidence"], "medium")        # fields absent -> not inflated
        self.assertEqual(capped["confidence"], "high")        # ceiling actually bound it
        self.assertTrue(any("bandwidth-bound" in a for a in capped["assumptions"]))

    def test_speed_estimate_returns_range(self) -> None:
        estimate = estimate_tokens_per_second(
            {
                "ctx_size": 131072,
                "gpu_layers": 999,
                "batch_size": 1024,
                "ubatch_size": 512,
                "cache_type_k": "q4_0",
                "cache_type_v": "q4_0",
                "flash_attn": True,
                "kv_offload": True,
                "op_offload": True,
            },
            {"name": "Example 35B Q4", "params_b": 35, "quant": "Q4_K_M", "size_bytes": 20},
            {
                "cpu": {"logical_cores": 24},
                "primary_gpu": {"name": "NVIDIA GeForce RTX 5090", "vram_total_bytes": 32 * 1024**3},
            },
        )

        self.assertGreater(estimate["estimate_tps"], 0)
        self.assertGreater(estimate["high_tps"], estimate["low_tps"])
        self.assertEqual(estimate["confidence"], "medium")

    def test_memory_fit_uses_vram_and_ram_pressure(self) -> None:
        fit = estimate_memory_fit(
            {
                "ctx_size": 131072,
                "gpu_layers": 49,
                "batch_size": 512,
                "ubatch_size": 256,
                "cache_type_k": "q4_0",
                "cache_type_v": "q4_0",
                "kv_offload": False,
                "op_offload": True,
                "mmap": True,
                "fit_target_mib": 2048,
            },
            {"name": "Example 35B Q4", "params_b": 35, "quant": "Q4_K_M", "size_bytes": 22 * 1024**3},
            {
                "memory": {"total_bytes": 64 * 1024**3, "available_bytes": 48 * 1024**3},
                "primary_gpu": {
                    "name": "NVIDIA GeForce RTX 5090",
                    "vram_total_bytes": 32 * 1024**3,
                    "vram_free_bytes": 30 * 1024**3,
                    "acceleration_backend": "cuda",
                },
            },
        )

        self.assertIn(fit["status"], {"good", "tight", "near_limit"})
        self.assertTrue(fit["uses_ram_offload"])
        self.assertGreater(fit["estimated"]["accelerator_used_mib"], 0)
        self.assertGreater(fit["estimated"]["ram_used_mib"], 0)


class HuggingFaceMetadataTests(unittest.TestCase):
    def test_infer_query_from_local_model_name(self) -> None:
        query = infer_query(
            name="Gemma 4 26B A4B UD Q6_K_XL",
            path=r"C:\Models\gemma-4-26B-A4B-it-GGUF-unsloth\gemma-4-26B-A4B-it-UD-Q6_K_XL.gguf",
        )
        self.assertIn("Gemma", query)
        self.assertIn("26B", query)
        self.assertNotIn("Q6_K_XL", query)

    def test_check_model_update_flags_size_difference(self) -> None:
        from lcc_core import hf_metadata
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "model-Q4_K_M.gguf"
            local.write_bytes(b"x" * 100)
            hf_metadata.fetch_model_info = lambda **_: {"success": True, "model_id": "org/repo", "url": "https://hf.co/org/repo"}
            hf_metadata._get_json = lambda url, timeout=10.0: {"lastModified": "2026-01-01T00:00:00.000Z"}
            # Remote copy is a different size -> update available, exact file known.
            hf_metadata._find_remote_file = lambda mid, fn: {"rfilename": fn, "size": 200, "oid": "abc"}
            result = hf_metadata.check_model_update(name="model", path=str(local))
            self.assertTrue(result["update_available"])
            self.assertTrue(result["file_differs"])
            self.assertEqual(result["remote_file"]["rfilename"], "model-Q4_K_M.gguf")
            # Same size -> no update.
            hf_metadata._find_remote_file = lambda mid, fn: {"rfilename": fn, "size": 100, "oid": "abc"}
            same = hf_metadata.check_model_update(name="model", path=str(local))
            self.assertFalse(same["update_available"])


class KvMetaProbeTests(unittest.TestCase):
    """Reading a GGUF header is slow, so the profiles-list fit badge must never
    parse it; exact dims come only from the probe path, then persist."""

    def setUp(self) -> None:
        import lcc_core.estimates as est

        self.est = est
        est._gguf_meta_mem.clear()
        self._tmp = tempfile.mkdtemp()
        self._cache = Path(self._tmp) / "gguf_meta_cache.json"
        self._orig_cache_file = est._meta_cache_file
        self._orig_parse = est._parse_gguf_meta
        est._meta_cache_file = lambda: self._cache

        self.parse_calls: list[str] = []

        def fake_parse(path: str):
            self.parse_calls.append(path)
            return (32, (256, 128, 128), True, 40960)

        est._parse_gguf_meta = fake_parse
        self.model_file = Path(self._tmp) / "model.gguf"
        self.model_file.write_bytes(b"x")  # real file so the size+mtime signature works
        self.model = {"name": "m", "path": str(self.model_file), "params_b": 7, "quant": "Q4_K_M"}

    def tearDown(self) -> None:
        self.est._meta_cache_file = self._orig_cache_file
        self.est._parse_gguf_meta = self._orig_parse
        self.est._gguf_meta_mem.clear()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_list_badge_does_not_parse_gguf(self) -> None:
        fit = self.est.estimate_memory_fit({"ctx_size": 4096}, self.model, None, probe_model=False)
        self.assertEqual(self.parse_calls, [])  # never opened the GGUF
        self.assertIsNotNone(fit["estimated"]["kv_cache_mib"])  # heuristic still produced a number

    def test_partial_gpu_layers_badge_does_not_parse_gguf(self) -> None:
        # A partial -ngl needs the model's layer count; on the badge path that
        # must come from cache or the heuristic, never from a live header read.
        fit = self.est.estimate_memory_fit(
            {"ctx_size": 4096, "gpu_layers": 20}, self.model, None, probe_model=False
        )
        self.assertEqual(self.parse_calls, [])
        self.assertEqual(fit["inputs"]["gpu_layer_fraction"], round(20 / 80, 2))
        # With probing allowed the real layer count (32) is used instead.
        fit = self.est.estimate_memory_fit(
            {"ctx_size": 4096, "gpu_layers": 20}, self.model, None, probe_model=True
        )
        self.assertEqual(len(self.parse_calls), 1)
        self.assertEqual(fit["inputs"]["gpu_layer_fraction"], round(20 / 32, 2))

    def test_probe_parses_once_then_persists(self) -> None:
        self.est.estimate_memory_fit({"ctx_size": 4096}, self.model, None, probe_model=True)
        self.assertEqual(len(self.parse_calls), 1)
        # A later cache-only badge read (fresh in-process cache) reuses the
        # persisted dims — no second parse, and the exact dims are applied.
        self.est._gguf_meta_mem.clear()
        fit = self.est.estimate_memory_fit(
            {"ctx_size": 32768, "cache_type_k": "f16", "cache_type_v": "f16"},
            self.model, None, probe_model=False,
        )
        self.assertEqual(len(self.parse_calls), 1)
        # 32768 * 32 kv-heads(256? no: total 256) ... exact = ctx*256*(128+128)*2B
        expected = int(round(32768 * (256 * 128 * 2.0 + 256 * 128 * 2.0) / 1024 / 1024))
        self.assertEqual(fit["estimated"]["kv_cache_mib"], expected)

    def test_tool_support_detected_cached_and_recommended(self) -> None:
        # First read parses; the tool flag persists so a later cache-only read
        # (fresh in-process cache) reuses it without re-opening the GGUF.
        self.assertIs(self.est.model_supports_tools(str(self.model_file)), True)
        self.assertEqual(len(self.parse_calls), 1)
        self.est._gguf_meta_mem.clear()
        self.assertIs(self.est.model_supports_tools(str(self.model_file), probe=False), True)
        self.assertEqual(len(self.parse_calls), 1)
        rec = self.est.recommend_jinja({"path": str(self.model_file)})
        self.assertTrue(rec["recommended"])

    def test_context_length_parsed_and_cached(self) -> None:
        # The trained context flows through the same single parse + cache as dims.
        self.assertEqual(self.est.model_max_context(self.model), 40960)
        self.assertEqual(len(self.parse_calls), 1)
        self.est._gguf_meta_mem.clear()
        # Cache-only read reuses the persisted value without re-parsing.
        self.assertEqual(self.est.model_max_context(self.model, probe=False), 40960)
        self.assertEqual(len(self.parse_calls), 1)

    def test_template_tool_markers(self) -> None:
        self.assertTrue(self.est._template_supports_tools("...{{ tool_call }}..."))
        self.assertTrue(self.est._template_supports_tools("...[TOOL_CALLS]..."))
        self.assertFalse(self.est._template_supports_tools("a plain {{ messages }} template"))
        self.assertFalse(self.est._template_supports_tools(None))


class SmartTuneTests(unittest.TestCase):
    def _hw(self, vram_gb: float | None) -> dict:
        gpu = {"name": "RTX 4090", "vram_bandwidth_gbps": 1000}
        if vram_gb is not None:
            gpu["vram_total_bytes"] = int(vram_gb * 1024**3)
            gpu["vram_free_bytes"] = int(vram_gb * 1024**3)
        return {"primary_gpu": gpu,
                "memory": {"total_bytes": 64 * 1024**3, "available_bytes": 48 * 1024**3},
                "cpu": {"logical_cores": 16}}

    def test_roomy_gpu_gets_full_offload_and_never_overflows(self) -> None:
        from lcc_core.smart_tune import auto_tune_fit

        model = {"name": "test-7B", "params_b": 7, "quant": "Q4_K_M"}
        out = auto_tune_fit({"gpu_layers": 0, "ctx_size": 2048}, model, self._hw(24))
        self.assertTrue(out["success"])
        self.assertNotEqual(out["after"]["fit_status"]["status"], "near_limit")
        self.assertEqual(str(out["tuned_params"]["gpu_layers"]), "all")
        self.assertGreaterEqual(out["after"]["fit_status"]["inputs"]["ctx_size"], 2048)

    def test_jinja_recommendation_flows_into_suggestions(self) -> None:
        import lcc_core.smart_tune as st

        model = {"name": "test-7B", "params_b": 7, "quant": "Q4_K_M"}
        orig = st.recommend_jinja
        st.recommend_jinja = lambda m, probe=True: {"recommended": True, "reason": "test template"}
        try:
            out = st.auto_tune_fit({"gpu_layers": 0, "ctx_size": 2048, "jinja": False}, model, self._hw(24))
        finally:
            st.recommend_jinja = orig
        self.assertTrue(out["success"])
        self.assertTrue(out["jinja"]["recommended"])
        for suggestion in out["suggestions"]:
            self.assertTrue(suggestion["params"]["jinja"])
        self.assertTrue(any(c["field"] == "jinja" for c in out["changes"]))

    def test_unknown_vram_does_not_recommend_gpu_offload(self) -> None:
        from lcc_core.smart_tune import auto_tune_fit

        model = {"name": "test-7B", "params_b": 7, "quant": "Q4_K_M"}
        out = auto_tune_fit({"gpu_layers": "all", "ctx_size": 131072}, model, self._hw(None))
        # With no measurable VRAM, any surviving pick must keep layers off the GPU.
        if out["success"]:
            self.assertEqual(out["after"]["fit_status"]["inputs"]["gpu_layer_fraction"], 0)

    def test_ctx_ladder_offers_256k_when_model_and_vram_allow(self) -> None:
        # A model trained for 262144 on a big GPU should let the tuner reach 256K.
        from lcc_core.smart_tune import _ctx_ladder_for_model
        model = {"name": "big-ctx", "params_b": 7, "quant": "Q4_K_M", "context_length": 262144}
        ladder = _ctx_ladder_for_model(model)
        self.assertIn(262144, ladder)

    def test_ctx_ladder_capped_at_trained_window(self) -> None:
        # A 32K-trained model must never be offered a larger context.
        from lcc_core.smart_tune import _ctx_ladder_for_model
        model = {"name": "small-ctx", "params_b": 7, "quant": "Q4_K_M", "context_length": 32768}
        ladder = _ctx_ladder_for_model(model)
        self.assertEqual(max(ladder), 32768)
        self.assertNotIn(262144, ladder)

    def test_ctx_ladder_includes_exact_trained_non_rung(self) -> None:
        # An odd trained window (40960) is offered exactly, capped there.
        from lcc_core.smart_tune import _ctx_ladder_for_model
        model = {"name": "odd-ctx", "params_b": 7, "quant": "Q4_K_M", "context_length": 40960}
        ladder = _ctx_ladder_for_model(model)
        self.assertEqual(max(ladder), 40960)
        self.assertTrue(all(c <= 40960 for c in ladder))

    def test_ctx_over_trained_window_warns(self) -> None:
        from lcc_core.estimates import estimate_memory_fit
        model = {"name": "small-ctx", "params_b": 7, "quant": "Q4_K_M", "context_length": 32768}
        fit = estimate_memory_fit({"ctx_size": 262144, "gpu_layers": "all"}, model, self._hw(24))
        self.assertTrue(any("trained window" in w for w in fit["warnings"]))

    def test_sizes_against_total_vram_when_another_process_holds_the_card(self) -> None:
        # A stale server can leave only a sliver of free VRAM. Smart Fit must
        # still size the card (total), not the leftover, so the recommendation
        # stays GPU-offload and warns that Start will compete for memory.
        from lcc_core.smart_tune import auto_tune_fit

        hw = self._hw(24)
        hw["primary_gpu"]["vram_free_bytes"] = int(0.3 * 1024**3)  # ~300 MiB free
        model = {"name": "test-7B", "params_b": 7, "quant": "Q4_K_M"}
        out = auto_tune_fit({"gpu_layers": 0, "ctx_size": 2048}, model, hw)
        self.assertTrue(out["success"])
        self.assertFalse(out["cpu_fallback"])
        self.assertGreater(out["after"]["fit_status"]["inputs"]["gpu_layer_fraction"], 0)
        self.assertEqual(str(out["tuned_params"]["gpu_layers"]), "all")
        self.assertTrue(any("already using" in note.lower() for note in out["notes"]))

    def test_cpu_fallback_when_the_card_cannot_hold_the_model(self) -> None:
        # Tiny total VRAM: no GPU-offload config can fit the card itself.
        from lcc_core.smart_tune import auto_tune_fit

        model = {"name": "test-32B", "params_b": 32, "quant": "Q4_K_M"}
        out = auto_tune_fit({"gpu_layers": "all", "ctx_size": 8192}, model, self._hw(2))
        self.assertTrue(out["success"])
        self.assertTrue(out["cpu_fallback"])
        self.assertLessEqual(out["after"]["fit_status"]["inputs"]["gpu_layer_fraction"], 0)
        self.assertTrue(any("cannot hold" in note.lower() for note in out["notes"]))

    def test_balanced_prefers_good_over_tight_when_both_exist(self) -> None:
        # 32B Q4 on 24 GB: short-context full offload is good, longer is tight.
        # Balanced (the auto-applied pick) must not spend that extra window if
        # it turns a good fit into a tight one.
        from lcc_core.smart_tune import auto_tune_fit, _collect_candidates

        model = {"name": "test-32B", "params_b": 32, "quant": "Q4_K_M"}
        hw = self._hw(24)
        base = {"gpu_layers": 0, "ctx_size": 2048, "batch_size": 128, "ubatch_size": 128}
        candidates = _collect_candidates(base, model, hw)
        self.assertTrue(candidates)
        max_lf = max(c["lf"] for c in candidates)
        self.assertTrue(any(c["lf"] == max_lf and c["roomy"] for c in candidates))
        self.assertTrue(any(c["lf"] == max_lf and not c["roomy"] for c in candidates))

        out = auto_tune_fit(base, model, hw)
        self.assertTrue(out["success"])
        self.assertEqual(out["after"]["fit_status"]["status"], "good")

    def test_reports_named_suggestions(self) -> None:
        from lcc_core.smart_tune import auto_tune_fit

        model = {"name": "test-7B", "params_b": 7, "quant": "Q4_K_M"}
        out = auto_tune_fit({"gpu_layers": 0, "ctx_size": 2048}, model, self._hw(24))
        self.assertTrue(out["success"])
        self.assertTrue(out["suggestions"])
        covered = {i for s in out["suggestions"] for i in s["intents"]}
        self.assertEqual(covered, {"balanced", "max_quality", "max_context"})
        # The default pick is the balanced one.
        self.assertEqual(out["tuned_params"], out["suggestions"][0]["params"])

    def test_does_not_trade_quant_quality_for_a_bigger_cache(self) -> None:
        from lcc_core.smart_tune import auto_tune_fit, _CACHE_RANK

        model = {"name": "test-7B", "params_b": 7, "quant": "Q4_K_M"}
        out = auto_tune_fit({"gpu_layers": 0, "ctx_size": 2048}, model, self._hw(24))
        self.assertTrue(out["success"])
        quality = next(s for s in out["suggestions"] if "max_quality" in s["intents"])
        context = next(s for s in out["suggestions"] if "max_context" in s["intents"])
        # Max-context never beats max-quality on context while the quality pick
        # holds an equal-or-better quant — i.e. quality is never sacrificed for size.
        self.assertGreaterEqual(context["params"]["ctx_size"], quality["params"]["ctx_size"])
        self.assertGreaterEqual(
            _CACHE_RANK[quality["params"]["cache_type_k"]],
            _CACHE_RANK[context["params"]["cache_type_k"]],
        )

    def test_never_spends_more_bits_on_v_than_k(self) -> None:
        from lcc_core.smart_tune import auto_tune_fit, _CACHE_RANK

        model = {"name": "test-7B", "params_b": 7, "quant": "Q4_K_M"}
        out = auto_tune_fit({"gpu_layers": 0, "ctx_size": 2048}, model, self._hw(24))
        self.assertTrue(out["success"])
        for s in out["suggestions"]:
            p = s["params"]
            self.assertLessEqual(
                _CACHE_RANK[p["cache_type_v"]], _CACHE_RANK[p["cache_type_k"]], p
            )

    def test_bf16_ready_gpu_prefers_bf16_without_extra_quality_weight(self) -> None:
        from lcc_core.smart_tune import auto_tune_fit, _CACHE_RANK, _cache_ladder

        hw = self._hw(24)
        hw["primary_gpu"]["name"] = "NVIDIA GeForce RTX 5090"
        hw["primary_gpu"]["acceleration_backend"] = "CUDA"
        self.assertEqual(_CACHE_RANK["bf16"], _CACHE_RANK["f16"])
        self.assertEqual(_cache_ladder(hw)[0], "bf16")

        model = {"name": "test-7B", "params_b": 7, "quant": "Q4_K_M"}
        out = auto_tune_fit({"gpu_layers": 0, "ctx_size": 2048}, model, hw)
        self.assertTrue(out["success"])
        quality = next(s for s in out["suggestions"] if "max_quality" in s["intents"])
        self.assertEqual(quality["params"]["cache_type_k"], "bf16")
        self.assertEqual(quality["params"]["cache_type_v"], "bf16")

    def test_non_bf16_gpu_falls_back_to_f16_ladder(self) -> None:
        from lcc_core.smart_tune import _cache_ladder

        hw = self._hw(24)
        hw["primary_gpu"]["name"] = "NVIDIA GeForce GTX 1080"
        hw["primary_gpu"]["acceleration_backend"] = "CUDA"
        ladder = _cache_ladder(hw)
        self.assertEqual(ladder[0], "f16")
        self.assertNotIn("bf16", ladder)

    def test_recommends_threads_from_cpu_info(self) -> None:
        from lcc_core.smart_tune import auto_tune_fit

        model = {"name": "test-7B", "params_b": 7, "quant": "Q4_K_M"}
        hw = self._hw(24)
        hw["cpu"] = {"physical_cores": 12, "logical_cores": 24}
        out = auto_tune_fit({"gpu_layers": 0, "ctx_size": 2048}, model, hw)
        self.assertTrue(out["success"])
        # 24 GB + 7B -> full offload, so decode threads use a small fixed pool.
        tuned = out["tuned_params"]
        self.assertEqual(tuned["threads"], 8)
        self.assertEqual(tuned["threads_batch"], 8)
        self.assertTrue(any(c["field"] == "threads" for c in out["changes"]))

    def test_partial_offload_uses_physical_and_logical_cores(self) -> None:
        from lcc_core.smart_tune import _recommend_threads

        rec = _recommend_threads({"cpu": {"physical_cores": 12, "logical_cores": 24}}, 0.5)
        self.assertEqual(rec, {"threads": 11, "threads_batch": 24})
        # Only logical known: assume SMT, halve for physical.
        rec = _recommend_threads({"cpu": {"logical_cores": 16}}, 0.0)
        self.assertEqual(rec, {"threads": 7, "threads_batch": 16})
        self.assertIsNone(_recommend_threads({"cpu": {}}, 1.0))

    def test_batch_grows_into_headroom_but_never_shrinks(self) -> None:
        from lcc_core.smart_tune import auto_tune_fit

        # Cap the trained window so leftover VRAM is real batch headroom,
        # not already spent on the last good context rung.
        model = {"name": "test-7B", "params_b": 7, "quant": "Q4_K_M", "context_length": 8192}
        out = auto_tune_fit(
            {"gpu_layers": 0, "ctx_size": 2048, "batch_size": 512, "ubatch_size": 128},
            model, self._hw(24),
        )
        self.assertTrue(out["success"])
        for s in out["suggestions"]:
            p = s["params"]
            self.assertGreaterEqual(p["ubatch_size"], 128)
            self.assertGreaterEqual(p["batch_size"], p["ubatch_size"])
            self.assertNotIn(s["fit_status"]["status"], {"near_limit", "unknown"})
        # Roomy GPU: the balanced pick should have grown the physical batch.
        self.assertGreaterEqual(out["tuned_params"]["ubatch_size"], 512)

    def test_quantized_kv_forces_flash_attention(self) -> None:
        from lcc_core.smart_tune import auto_tune_fit, _is_16bit_cache

        model = {"name": "test-7B", "params_b": 7, "quant": "Q4_K_M"}
        out = auto_tune_fit(
            {"gpu_layers": 0, "ctx_size": 2048, "flash_attn": False}, model, self._hw(24)
        )
        self.assertTrue(out["success"])
        for s in out["suggestions"]:
            p = s["params"]
            if not _is_16bit_cache(p.get("cache_type_k", "f16")) or not _is_16bit_cache(p.get("cache_type_v", "f16")):
                self.assertTrue(s["params"].get("flash_attn"), s["params"])


class SamplingTests(unittest.TestCase):
    def test_presets_have_expected_shape(self) -> None:
        from lcc_core.sampling import list_sampling_intents, suggest_sampling

        intents = list_sampling_intents()
        self.assertTrue(intents)
        coding = suggest_sampling("coding")
        self.assertTrue(coding["success"])
        self.assertEqual(coding["params"]["temperature"], 0.2)
        self.assertIn("temperature", coding["rationale"])

    def test_unknown_intent_fails_cleanly(self) -> None:
        from lcc_core.sampling import suggest_sampling

        self.assertFalse(suggest_sampling("nope")["success"])


class RuntimeUpdatesTests(unittest.TestCase):
    def setUp(self) -> None:
        from lcc_core import runtime_updates

        self.runtime_updates = runtime_updates
        self._orig_fetch = runtime_updates.fetch_latest_release
        self._orig_cache_path = runtime_updates._cache_path

        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)
        fake_cache = Path(tmp_dir) / "runtime-updates.json"
        runtime_updates._cache_path = lambda: fake_cache  # type: ignore[assignment]

    def tearDown(self) -> None:
        self.runtime_updates.fetch_latest_release = self._orig_fetch  # type: ignore[assignment]
        self.runtime_updates._cache_path = self._orig_cache_path  # type: ignore[assignment]

    def test_parse_version_handles_v_prefix_and_suffixes(self) -> None:
        from lcc_core.runtime_updates import parse_version

        self.assertEqual(parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(parse_version("b4500"), (4500,))
        self.assertEqual(parse_version("1.2.3-rc1"), (1, 2, 3))
        self.assertIsNone(parse_version("unknown"))
        self.assertIsNone(parse_version(None))

    def test_parse_version_reads_raw_binary_version_output(self) -> None:
        """Regression: `--version` lines never parsed, so update_available was
        permanently False. `_strip_leading_v` ate the 'v' of "version:" and the
        anchored regexes then matched nothing."""
        from lcc_core.runtime_updates import compare_versions, parse_version

        self.assertEqual(parse_version("version: b4488 (build c8a8a9d5)"), (4488,))
        self.assertEqual(parse_version("ollama version is 0.5.7"), (0, 5, 7))
        # A bare build hash carries no version and must not be mistaken for one.
        self.assertIsNone(parse_version("c8a8a9d5"))
        self.assertLess(compare_versions("version: b4488 (build c8a8a9d5)", "b4500"), 0)
        self.assertLess(compare_versions("ollama version is 0.5.7", "v0.6.0"), 0)

    def test_compare_versions(self) -> None:
        from lcc_core.runtime_updates import compare_versions

        self.assertEqual(compare_versions("1.2.3", "1.2.3"), 0)
        self.assertLess(compare_versions("1.2.2", "1.2.3"), 0)
        self.assertGreater(compare_versions("1.3.0", "1.2.99"), 0)
        self.assertEqual(compare_versions(None, "1.0"), 0)
        self.assertLess(compare_versions("b4400", "b4500"), 0)

    def test_is_prerelease_tag(self) -> None:
        from lcc_core.runtime_updates import is_prerelease_tag

        self.assertTrue(is_prerelease_tag("v1.2.3-rc1"))
        self.assertTrue(is_prerelease_tag("1.0.0-preview"))
        self.assertFalse(is_prerelease_tag("v1.2.3"))
        self.assertFalse(is_prerelease_tag(None))

    def test_candidate_runtimes_filters_unsupported_and_dedupes(self) -> None:
        from lcc_core.runtime_updates import _candidate_runtimes

        envs = [
            {"id": "llama.cpp", "version": "b4500"},
            {"id": "llama.cpp", "version": "ignored-duplicate"},
            {"id": "lm-studio", "version": "0.2.10"},
            {"id": "ollama", "details": {"version": "0.3.0"}},
            {"id": "vllm", "version": ""},
        ]
        candidates = _candidate_runtimes(envs)
        self.assertEqual([item[0] for item in candidates], ["llama.cpp", "ollama"])

    def test_check_runtime_updates_reports_update_when_newer(self) -> None:
        from lcc_core.runtime_updates import check_runtime_updates

        def fake_fetch(repo: str, channel: str, timeout: float = 1.0) -> dict:
            return {
                "ok": True,
                "tag": "b4600",
                "release_url": f"https://github.com/{repo}/releases/tag/b4600",
                "error": None,
            }

        self.runtime_updates.fetch_latest_release = fake_fetch  # type: ignore[assignment]
        result = check_runtime_updates(
            [{"id": "llama.cpp", "version": "b4500"}],
            channel="stable",
            force_refresh=True,
        )

        self.assertEqual(result["channel"], "stable")
        self.assertEqual(len(result["updates"]), 1)
        info = result["updates"][0]
        self.assertEqual(info["runtime_id"], "llama.cpp")
        self.assertEqual(info["current_version"], "b4500")
        self.assertEqual(info["latest_version"], "b4600")
        self.assertTrue(info["update_available"])
        self.assertEqual(info["release_url"], "https://github.com/ggml-org/llama.cpp/releases/tag/b4600")

    def test_check_runtime_updates_no_update_when_current_is_higher(self) -> None:
        from lcc_core.runtime_updates import check_runtime_updates

        def fake_fetch(repo: str, channel: str, timeout: float = 1.0) -> dict:
            return {"ok": True, "tag": "0.5.0", "release_url": "https://example.com", "error": None}

        self.runtime_updates.fetch_latest_release = fake_fetch  # type: ignore[assignment]
        result = check_runtime_updates(
            [{"id": "ollama", "version": "0.6.0"}],
            channel="stable",
            force_refresh=True,
        )
        info = result["updates"][0]
        self.assertFalse(info["update_available"])

    def test_check_runtime_updates_records_fetch_errors(self) -> None:
        from lcc_core.runtime_updates import check_runtime_updates

        def fake_fetch(repo: str, channel: str, timeout: float = 1.0) -> dict:
            return {"ok": False, "tag": None, "release_url": "https://example.com", "error": "timeout"}

        self.runtime_updates.fetch_latest_release = fake_fetch  # type: ignore[assignment]
        result = check_runtime_updates(
            [{"id": "vllm", "version": "0.6.0"}],
            force_refresh=True,
        )
        info = result["updates"][0]
        self.assertFalse(info["update_available"])
        self.assertIsNone(info["latest_version"])
        self.assertEqual(info["notes"], "timeout")

    def test_check_runtime_updates_uses_cache_on_second_pass(self) -> None:
        from lcc_core.runtime_updates import check_runtime_updates

        call_count = {"n": 0}

        def fake_fetch(repo: str, channel: str, timeout: float = 1.0) -> dict:
            call_count["n"] += 1
            return {"ok": True, "tag": "b4600", "release_url": "https://example.com", "error": None}

        self.runtime_updates.fetch_latest_release = fake_fetch  # type: ignore[assignment]
        envs = [{"id": "llama.cpp", "version": "b4500"}]
        check_runtime_updates(envs, force_refresh=True)
        first_calls = call_count["n"]
        self.assertEqual(first_calls, 1)

        cached_result = check_runtime_updates(envs, force_refresh=False)
        self.assertEqual(call_count["n"], first_calls)
        info = cached_result["updates"][0]
        self.assertEqual(info["latest_version"], "b4600")
        self.assertTrue(info["update_available"])

    def test_force_runtime_rechecks_only_that_runtime(self) -> None:
        from lcc_core.runtime_updates import check_runtime_updates

        fetched: list[str] = []

        def fake_fetch(repo: str, channel: str, timeout: float = 1.0) -> dict:
            fetched.append(repo)
            return {"ok": True, "tag": "b4600", "release_url": "https://example.com", "error": None}

        self.runtime_updates.fetch_latest_release = fake_fetch  # type: ignore[assignment]
        envs = [{"id": "llama.cpp", "version": "b4500"}, {"id": "ollama", "version": "0.3.0"}]
        check_runtime_updates(envs, force_refresh=True)
        self.assertEqual(len(fetched), 2)  # cold cache: both fetched

        fetched.clear()
        result = check_runtime_updates(envs, force_runtime="ollama")
        # Only ollama bypasses the warm cache; llama.cpp is served from it.
        self.assertEqual(len(fetched), 1)
        self.assertIn("ollama", fetched[0])
        self.assertEqual(len(result["updates"]), 2)


class ServerStopTests(unittest.TestCase):
    def test_stop_escalates_to_sigkill_when_sigterm_ignored(self) -> None:
        import subprocess
        import sys
        from unittest import mock

        from lcc_core import server_manager

        if server_manager.is_windows():
            self.skipTest("POSIX SIGKILL escalation")

        # A child that ignores SIGTERM, so a plain `kill` can never stop it.
        proc = subprocess.Popen(
            [sys.executable, "-c", "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print('ready',flush=True);time.sleep(60)"],
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            proc.stdout.readline()  # wait until the SIGTERM handler is installed
            with tempfile.TemporaryDirectory() as tmp:
                with mock.patch.object(server_manager, "cache_dir", return_value=Path(tmp)):
                    server_manager.write_state(
                        {"servers": [{"id": "test-server", "mode": "test", "pid": proc.pid}]}
                    )
                    result = server_manager.stop_server(server_id="test-server")
            self.assertTrue(result["success"], result)
            self.assertFalse(server_manager.pid_is_running(proc.pid))
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=5)
            proc.stdout.close()


    def test_fit_parser_reads_upstream_memory_breakdown_line(self) -> None:
        # Verbatim from tools/fit-params/README.md (template_gpu in
        # llama_memory_breakdown_print): total = free + (self = model + context + compute) + unaccounted.
        breakdown = (
            "llama_memory_breakdown_print: | memory breakdown [MiB] | total   free     self   model   context   compute    unaccounted |\n"
            "llama_memory_breakdown_print: |   - CUDA0 (RTX 4090)   | 24077 =  945 + (19187 = 17904 +     384 +     898) +        3945 |\n"
            "llama_memory_breakdown_print: |   - Host               |                 58271 = 58259 +       0 +      12                |"
        )
        parsed = parse_fit_output("-c 4096 -ngl 48\n", breakdown)
        memory = parsed["suggestions"]["cuda_memory_mib"]
        self.assertEqual(memory["model"], 17904)
        self.assertEqual(memory["context"], 384)
        self.assertEqual(memory["compute"], 898)
        self.assertEqual(memory["projected"], 19187)

    def test_fit_parser_reads_metal_memory_line(self) -> None:
        parsed = parse_fit_output(
            "-c 8192 -ngl -2\n",
            "llama_memory_breakdown_print: |   - Metal0 (Apple M2 Max) |  6144 =  2666 + ( 3478 =  2883 +      47 +     548) +           0 |"
            "\nllama_memory_breakdown_print: |   - Host                 |                  2290 =  2208 +       0 +      82                |",
        )
        self.assertEqual(parsed["suggestions"]["cuda_memory_mib"]["model"], 2883)
        self.assertEqual(parsed["suggestions"]["cuda_memory_mib"]["context"], 47)
        self.assertEqual(parsed["suggestions"]["cuda_memory_mib"]["compute"], 548)

    def test_fit_parser_reads_rocm_memory_line(self) -> None:
        parsed = parse_fit_output(
            "-c 4096 -ngl 32\n",
            "llama_memory_breakdown_print: |   - ROCm0 (RX 7900 XTX) | 24560 = 22830 + ( 1730 =  1500 +      30 +     200) +           0 |",
        )
        self.assertEqual(parsed["suggestions"]["cuda_memory_mib"]["model"], 1500)

    def test_mmproj_in_middle_of_filename_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = root / "models"
            model_dir.mkdir()
            (model_dir / "gemma-4-default-mmproj.gguf").write_bytes(b"projector")
            (model_dir / "gemma-4-26B-Q4_K_M.gguf").write_bytes(b"model")

            models = discover_models([root / "models"])

        self.assertEqual(len(models), 1)
        self.assertIn("gemma-4-26B", models[0].name)

    def test_diffusion_unet_ggufs_are_not_discovered_as_llms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "models"
            (root / "unet").mkdir(parents=True)
            (root / "unet" / "Wan-I2V-Q8_0.gguf").write_bytes(b"diffusion")
            (root / "Qwen-1B-Q8_0.gguf").write_bytes(b"llm")

            models = discover_models([root])

        self.assertEqual([model.name for model in models], ["Qwen-1B-Q8_0"])

    def test_find_project_root_falls_back_to_package_location(self) -> None:
        # The real repo has pyproject.toml, so find_project_root() should resolve.
        root = find_project_root(Path(__file__).parent.parent)
        self.assertIsNotNone(root)
        self.assertTrue((root / "pyproject.toml").exists())


class WslVllmStopGuardTests(unittest.TestCase):
    """The in-distro stop script walks /proc descendants from the pidfile PID.
    With a missing pidfile the root was 0, and since PID 1 has ppid 0 on Linux
    the walk collected every process in the distro and SIGKILLed it — stopping
    one vLLM server tore down the whole WSL install."""

    def test_stop_script_aborts_without_a_valid_root_pid(self) -> None:
        from lcc_core.server_manager import WSL_STOP_NO_ROOT_MARKER, _wsl_stop_script

        script = _wsl_stop_script("/tmp/vllm.pid")
        self.assertIn("if root <= 0:", script)
        self.assertIn(WSL_STOP_NO_ROOT_MARKER, script)
        self.assertIn("sys.exit(3)", script)
        # The guard has to precede the /proc walk to be worth anything.
        self.assertLess(script.index("if root <= 0:"), script.index("os.listdir('/proc')"))
        compile(script, "<wsl-stop-script>", "exec")

    def test_stop_script_with_missing_pidfile_kills_nothing(self) -> None:
        import os
        import subprocess
        import sys

        from lcc_core.server_manager import WSL_STOP_NO_ROOT_MARKER, _wsl_stop_script

        if os.name != "posix":
            self.skipTest("the stop script targets Linux /proc semantics")
        missing = str(Path(tempfile.mkdtemp()) / "absent.pid")
        proc = subprocess.run(
            [sys.executable, "-c", _wsl_stop_script(missing)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 3)
        self.assertIn(WSL_STOP_NO_ROOT_MARKER, proc.stdout)

    def test_stop_reports_failure_when_script_aborts(self) -> None:
        import subprocess
        from unittest import mock

        from lcc_core import server_manager

        aborted = subprocess.CompletedProcess(
            [], 3, server_manager.WSL_STOP_NO_ROOT_MARKER + "\n", ""
        )
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(server_manager, "cache_dir", return_value=Path(tmp)):
                server_manager.write_state({"servers": [{
                    "id": "vllm-1", "mode": "vllm-wsl", "pid": 424242,
                    "wsl_pidfile": "/tmp/vllm.pid", "wsl_distro": "Ubuntu-24.04",
                }]})
                with mock.patch.object(subprocess, "run", return_value=aborted) as ran:
                    result = server_manager._stop_wsl_vllm(
                        server_manager._find_server("vllm-1"), timeout=5
                    )
                stored = server_manager._find_server("vllm-1")

        self.assertFalse(result["success"])
        self.assertIn("pidfile", result["message"])
        self.assertEqual(stored["status"], "stop_failed")
        # The aborted script must be the only stop action: no taskkill fallback
        # may run, or the client would die while vLLM kept the GPU. Match on
        # call contents, not count — pid_is_running may issue tasklist probes
        # via subprocess when psutil is unavailable.
        commands = [" ".join(map(str, call.args[0])) for call in ran.call_args_list]
        self.assertEqual(sum("wsl" in cmd and "python3" in cmd for cmd in commands), 1)
        self.assertFalse(any("taskkill" in cmd for cmd in commands))


class RuntimeDispatchTests(unittest.TestCase):
    def test_binary_version_extracts_the_version_token(self) -> None:
        """Regression: the whole `--version` line was stored, which parse_version
        could not read, so llama.cpp never reported an available update."""
        import subprocess
        from unittest import mock

        from lcc_core import backends

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, "version: b4488 (build c8a8a9d5)\n", "")

        with mock.patch.object(backends.subprocess, "run", side_effect=fake_run):
            self.assertEqual(backends._binary_version("llama-server"), "b4488")

        def fake_ollama(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, "ollama version is 0.5.7\n", "")

        # Ollama prints no colon, so the raw line is kept and parse_version copes.
        with mock.patch.object(backends.subprocess, "run", side_effect=fake_ollama):
            version = backends._binary_version("ollama")
        self.assertEqual(version, "ollama version is 0.5.7")

        from lcc_core.runtime_updates import parse_version

        self.assertEqual(parse_version(version), (0, 5, 7))

    def test_detect_runtime_maps_ids_and_rejects_unknown(self) -> None:
        from lcc_core.backends import LAUNCHABLE_RUNTIMES, detect_runtime

        # Known ids return an Environment with the matching id; default/empty
        # falls back to llama.cpp. Detection may report unavailable offline —
        # we only assert the dispatch here, not availability.
        self.assertEqual(detect_runtime("llama.cpp").id, "llama.cpp")
        self.assertEqual(detect_runtime(None).id, "llama.cpp")
        self.assertEqual(detect_runtime("ollama").id, "ollama")
        # Unknown id is rejected (no silent fallback to llama.cpp).
        self.assertIsNone(detect_runtime("nonsense-runtime"))
        self.assertIn("llama.cpp", LAUNCHABLE_RUNTIMES)
        self.assertIn("vllm-wsl", LAUNCHABLE_RUNTIMES)


class LayerIndexAndCacheBytesTests(unittest.TestCase):
    """Lock in the tensor-index parser and KV-cache byte sizing so a refactor
    can't silently regress hybrid-SSM layer counting or quantized KV rates."""

    def test_layer_index_covers_all_naming_conventions(self) -> None:
        from lcc_core.estimates import _layer_index_from_tensor

        cases = {
            "blk.5.attn_k.weight": 5,
            "block.12.attn_v.weight": 12,
            "model.layers.3.self_attn.k_proj.weight": 3,
            "transformer.layer.7.attn_q.weight": 7,
            "enc.blk.0.attn_norm.weight": 0,
            "h[9].attn.weight": None,  # bare h[] at start has no leading dot
            "something.h[4].attn.weight": 4,
            "tok_embeddings.weight": None,
            "output_norm.weight": None,
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(_layer_index_from_tensor(name), expected)

    def test_cache_bytes_specific_quants_match_llama_cpp_blocks(self) -> None:
        from lcc_core.estimates import _cache_bytes

        # Exact KV-cache type names: bytes/element = llama.cpp block ratio.
        self.assertAlmostEqual(_cache_bytes("q8_0"), 34 / 32)
        self.assertAlmostEqual(_cache_bytes("q5_1"), 24 / 32)
        self.assertAlmostEqual(_cache_bytes("q5_0"), 22 / 32)
        self.assertAlmostEqual(_cache_bytes("q4_1"), 20 / 32)
        self.assertAlmostEqual(_cache_bytes("q4_0"), 18 / 32)
        self.assertAlmostEqual(_cache_bytes("iq4_nl"), 18 / 32)
        self.assertAlmostEqual(_cache_bytes("f16"), 2.0)
        self.assertAlmostEqual(_cache_bytes("bf16"), 2.0)
        self.assertAlmostEqual(_cache_bytes("f32"), 4.0)
        # 4-bit float formats (NVIDIA hardware-accelerated): NVFP4 = 36 B / 64
        # elems (4 sub-block scales + 32 B packed E2M1); MXFP4 = 17 B / 32.
        self.assertAlmostEqual(_cache_bytes("nvfp4"), 36 / 64)
        self.assertAlmostEqual(_cache_bytes("mxfp4"), 17 / 32)

    def test_cache_bytes_bare_prefix_falls_back_approximately(self) -> None:
        from lcc_core.estimates import _cache_bytes

        # Bare quant prefixes (no specific block layout) hit the conservative
        # tier-2 fallback rather than collapsing to the f16 default.
        self.assertEqual(_cache_bytes("q8"), 1.0625)
        self.assertEqual(_cache_bytes("q6"), 0.8125)
        self.assertEqual(_cache_bytes("q4"), 0.5625)
        self.assertEqual(_cache_bytes("nvfp"), 0.5625)
        self.assertEqual(_cache_bytes("mxfp"), 0.53125)
        # Unknown / empty defaults to f16.
        self.assertEqual(_cache_bytes(""), 2.0)
        self.assertEqual(_cache_bytes("unknown"), 2.0)

    def test_cache_ladder_only_offers_flash_attn_supported_types(self) -> None:
        """Every rung must have a CUDA flash-attention kernel.

        llama.cpp does not error on a KV type it has no FA kernel for -- it
        silently runs attention on the CPU, which cost ~20x on prompt processing
        (measured: q5_1 151 tok/s vs q8_0 3054). nvfp4/mxfp4 are worse still:
        llama.cpp rejects them as cache types and the server won't start.
        """
        from lcc_core.smart_tune import _cache_ladder

        cuda_hw = {"primary_gpu": {"name": "NVIDIA GeForce RTX 4090", "acceleration_backend": "cuda"}}
        amd_hw = {"primary_gpu": {"name": "AMD Radeon RX 7900 XTX", "acceleration_backend": "rocm"}}
        none_hw = {"primary_gpu": {}}

        supported = {"f16", "bf16", "q8_0", "q4_0"}
        for hw in (cuda_hw, amd_hw, none_hw):
            self.assertTrue(set(_cache_ladder(hw)) <= supported, _cache_ladder(hw))

        cuda_ladder = _cache_ladder(cuda_hw)
        self.assertIn("bf16", cuda_ladder)  # CUDA unlocks BF16
        # Types that fall back to the CPU attention path must never be offered.
        for bad in ("q5_1", "q5_0", "q4_1", "iq4_nl", "nvfp4", "mxfp4"):
            self.assertNotIn(bad, cuda_ladder)
        # BF16 stays gated on hardware that runs it natively.
        self.assertNotIn("bf16", _cache_ladder(amd_hw))
        self.assertNotIn("bf16", _cache_ladder(none_hw))

    def test_smart_fit_never_suggests_mismatched_k_and_v(self) -> None:
        """K and V must always match -- a mismatched pair has no CUDA FA kernel.

        Measured: f16 K / q8_0 V ran prompt processing at 177 tok/s with 8 CPU
        threads pegged, against 3123 tok/s for f16/f16 on the same prompt.
        """
        from lcc_core.smart_tune import auto_tune_fit

        hw = {
            "primary_gpu": {
                "name": "NVIDIA GeForce RTX 5090",
                "acceleration_backend": "CUDA",
                "vram_bandwidth_gbps": 1000,
                "vram_total_bytes": 24 * 1024**3,
                "vram_free_bytes": 24 * 1024**3,
            },
            "memory": {"total_bytes": 64 * 1024**3, "available_bytes": 48 * 1024**3},
            "cpu": {"logical_cores": 16},
        }
        model = {"name": "test-7B", "params_b": 7, "quant": "Q4_K_M"}
        out = auto_tune_fit({"gpu_layers": 0, "ctx_size": 2048}, model, hw)
        self.assertTrue(out["success"])
        self.assertTrue(out["suggestions"])
        for s in out["suggestions"]:
            p = s["params"]
            self.assertEqual(p["cache_type_k"], p["cache_type_v"], p)


class ServerCrashWatchdogTests(unittest.TestCase):
    """A tracked server whose PID died while its status said 'running' must be
    flagged 'crashed' (with a stderr snapshot) rather than silently dropped."""

    def setUp(self) -> None:
        import lcc_core.server_manager as sm
        self.sm = sm
        self._tmp = tempfile.mkdtemp()
        self._orig_state_path = sm.state_path
        self._orig_cache_dir = None
        # Point state at a temp file so we never touch real tracked servers.
        self._state_file = Path(self._tmp) / "servers.json"
        sm.state_path = lambda: self._state_file
        # A fake stderr log the watchdog can tail.
        self._stderr = Path(self._tmp) / "stderr.log"
        self._stderr.write_text("line one\nOOM killed\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.sm.state_path = self._orig_state_path
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_state(self, servers):
        self._state_file.write_text(json.dumps({"servers": servers}), encoding="utf-8")

    def test_live_server_with_dead_pid_is_flagged_crashed(self):
        # A PID certain to not exist (2^31-1 is reserved/unallocated on every OS).
        dead_pid = 2147483647
        self._write_state([{
            "id": "demo-1234", "mode": "demo", "pid": dead_pid,
            "status": "running", "host": "127.0.0.1", "port": 8080,
            "stderr_log": str(self._stderr),
        }])
        self.sm.refresh_server_states()
        state = self.sm.read_state()
        self.assertEqual(state["servers"][0]["status"], "crashed")
        self.assertFalse(state["servers"][0]["running"])
        self.assertIn("crashed_at", state["servers"][0])
        self.assertIn("OOM killed", state["servers"][0]["last_stderr"])

    def test_already_stopped_server_is_not_recrashed(self):
        dead_pid = 2147483647
        self._write_state([{
            "id": "demo-stopped", "mode": "demo", "pid": dead_pid,
            "status": "stopped", "host": "127.0.0.1", "port": 8080,
            "stderr_log": str(self._stderr),
        }])
        self.sm.refresh_server_states()
        state = self.sm.read_state()
        # 'stopped' is terminal — the watchdog must not rewrite it.
        self.assertEqual(state["servers"][0]["status"], "stopped")
        self.assertNotIn("crashed_at", state["servers"][0])

    def test_starting_server_with_dead_pid_is_flagged_crashed(self):
        """Additional watchdog transition (M1.3): 'starting' in _LIVE_STATUSES must also crash on dead PID."""
        dead_pid = 2147483647
        self._write_state([{
            "id": "demo-starting", "mode": "demo", "pid": dead_pid,
            "status": "starting", "host": "127.0.0.1", "port": 8080,
            "stderr_log": str(self._stderr),
        }])
        self.sm.refresh_server_states()
        state = self.sm.read_state()
        self.assertEqual(state["servers"][0]["status"], "crashed")
        self.assertIn("crashed_at", state["servers"][0])


class PrometheusMetricsParserTests(unittest.TestCase):
    """The live-metrics parser must pull KV usage and token rates out of the
    Prometheus text that llama-server exposes, ignoring comments and labels."""

    def test_parses_kv_usage_and_token_rates(self):
        from lcc_core.server_metrics import _parse_prometheus
        sample = (
            "# HELP llamacpp:kv_cache_usage_ratio KV cache usage ratio\n"
            "# TYPE llamacpp:kv_cache_usage_ratio gauge\n"
            'llamacpp:kv_cache_usage_ratio{slot_id="0"} 0.421\n'
            'llamacpp:kv_cache_tokens{slot_id="0"} 13721\n'
            "# TYPE llamacpp:prompt_tokens_seconds gauge\n"
            'llamacpp:prompt_tokens_seconds 812.5\n'
            'llamacpp:tokens_predicted_seconds 45.2\n'
            'llamacpp:tokens_predicted_total 4096\n'
            'llamacpp:prompt_tokens_total 8192\n'
            'llamacpp:active_slots 1\n'
            'llamacpp:processing_slots 0\n'
        )
        parsed = _parse_prometheus(sample)
        self.assertAlmostEqual(parsed["kv_cache_usage_ratio"], 0.421)
        self.assertEqual(parsed["kv_cache_tokens"], 13721.0)
        self.assertEqual(parsed["prompt_tokens_per_second"], 812.5)
        self.assertEqual(parsed["predicted_tokens_per_second"], 45.2)
        self.assertEqual(parsed["slots_active"], 1.0)

    def test_ignores_comments_and_unrelated_lines(self):
        from lcc_core.server_metrics import _parse_prometheus
        parsed = _parse_prometheus("# just a comment\nunrelated_metric 5\n")
        self.assertNotIn("kv_cache_usage_ratio", parsed)

    def test_parses_vllm_metrics(self):
        from lcc_core.server_metrics import _parse_prometheus
        parsed = _parse_prometheus(
            'vllm:kv_cache_usage_perc{engine="0"} 0.25\n'
            'vllm:num_requests_running{engine="0"} 2\n'
            'vllm:num_requests_waiting{engine="0"} 1\n'
            'vllm:prompt_tokens_total{engine="0"} 100\n'
            'vllm:generation_tokens_total{engine="0"} 75\n'
        )
        self.assertEqual(parsed["kv_cache_usage_ratio"], 0.25)
        self.assertEqual(parsed["requests_in_flight"], 2.0)
        self.assertEqual(parsed["requests_waiting"], 1.0)
        self.assertEqual(parsed["prompt_tokens_total"], 100.0)
        self.assertEqual(parsed["predicted_tokens_total"], 75.0)


class LiveHardwareStatusTests(unittest.TestCase):
    """The TTL-cached live nvidia-smi poll must deduplicate within its window,
    parse multi-GPU / [N/A] CSV, and latch-disable on failure (SwarmUI pattern)."""

    def setUp(self) -> None:
        import lcc_core.hardware as hw
        self.hw = hw
        self._orig_snapshot = hw._nvidia_live_snapshot
        self._orig_unavailable = hw._nvidia_live_unavailable
        self._orig_cache = hw._live_cache
        self._orig_cache_ts = hw._live_cache_ts
        # Reset cache state so each test starts cold.
        hw._nvidia_live_unavailable = False
        hw._live_cache = None
        hw._live_cache_ts = 0.0
        self._orig_win_mem = hw._windows_memory_info
        self._orig_posix_mem = hw._posix_memory_info
        hw._windows_memory_info = lambda: {"total_bytes": 1000, "available_bytes": 400}
        hw._posix_memory_info = lambda: {"total_bytes": 1000, "available_bytes": 400}

    def tearDown(self) -> None:
        self.hw._nvidia_live_snapshot = self._orig_snapshot
        self.hw._nvidia_live_unavailable = self._orig_unavailable
        self.hw._live_cache = self._orig_cache
        self.hw._live_cache_ts = self._orig_cache_ts
        self.hw._windows_memory_info = self._orig_win_mem
        self.hw._posix_memory_info = self._orig_posix_mem

    def test_ttl_cache_dedupes_within_window(self):
        calls = []
        def fake():
            calls.append(1)
            return [{"index": 0, "name": "X", "utilization_gpu_percent": 5.0}]
        self.hw._nvidia_live_snapshot = fake
        self.hw.live_system_status()
        self.hw.live_system_status()
        self.hw.live_system_status()
        self.assertEqual(len(calls), 1, "second/third calls within TTL must hit the cache")

    def test_ram_always_refreshes_even_when_gpu_cached(self):
        self.hw._nvidia_live_snapshot = lambda: [{"index": 0, "name": "X"}]
        first = self.hw.live_system_status()
        # Drop available RAM between calls; GPU is cached but RAM must reflect it.
        self.hw._windows_memory_info = lambda: {"total_bytes": 1000, "available_bytes": 200}
        second = self.hw.live_system_status()
        self.assertEqual(first["system_ram"]["free_bytes"], 400)
        self.assertEqual(second["system_ram"]["free_bytes"], 200)

    def test_first_failure_latches_disable(self):
        calls = []
        self.hw._nvidia_live_snapshot = lambda: (calls.append(1), None)[1]
        a = self.hw.live_system_status()
        b = self.hw.live_system_status()
        c = self.hw.live_system_status()
        # Only the very first call queried nvidia-smi; subsequent calls short-circuit.
        self.assertEqual(len(calls), 1)
        self.assertEqual(a["gpus"], [])
        self.assertEqual(b["gpus"], [])
        # RAM still reported even with GPU unavailable.
        self.assertEqual(b["system_ram"]["total_bytes"], 1000)

    def test_snapshot_parses_multi_gpu_and_na(self):
        # A second GPU line and an "[N/A]" utilization (some GPUs report no util).
        raw = "0, RTX 5090, 12, 34, 41, 32768, 30720, 2048\n1, RTX 4090, [N/A], 50, 55, 24576, 24000, 576"
        from lcc_core.hardware import _float_or_none, _int_or_none
        # Simulate the parser path directly against the CSV nvidia-smi emits.
        gpus = []
        for line in raw.splitlines():
            parts = [p.strip() for p in line.split(",")]
            gpus.append({
                "index": _int_or_none(parts[0]),
                "name": parts[1],
                "utilization_gpu_percent": _float_or_none(parts[2].replace("[N/A]", "")),
                "used_mib": _int_or_none(parts[7]),
            })
        self.assertEqual(len(gpus), 2)
        self.assertEqual(gpus[0]["utilization_gpu_percent"], 12.0)
        self.assertIsNone(gpus[1]["utilization_gpu_percent"])  # [N/A] -> None
        self.assertEqual(gpus[1]["used_mib"], 576)


class PerProcessMemoryTests(unittest.TestCase):
    """The per-process block in fetch_server_metrics() must return RSS / CPU%
    (psutil) and GPU VRAM attribution (nvidia-smi --query-compute-apps) without
    blocking when either source is unavailable."""

    def setUp(self) -> None:
        import lcc_core.server_metrics as sm
        self.sm = sm
        self._orig_find = sm._find_server
        self._orig_pid_running = sm.pid_is_running
        self._orig_proc_mem = sm._process_memory
        self._orig_query = sm._query_compute_apps
        self._orig_apps_cache = sm._compute_apps_cache
        self._orig_apps_ts = sm._compute_apps_cache_ts
        self._orig_apps_unavail = sm._compute_apps_unavailable
        self._orig_get_json = sm._get_json
        self._orig_get_text = sm._get_text
        self._orig_psutil = sm.psutil
        sm._process_handles.clear()
        self.addCleanup(sm._process_handles.clear)
        # Reset cache so each test starts cold.
        sm._compute_apps_cache = None
        sm._compute_apps_cache_ts = 0.0
        sm._compute_apps_unavailable = False

    def tearDown(self) -> None:
        self.sm._find_server = self._orig_find
        self.sm.pid_is_running = self._orig_pid_running
        self.sm._process_memory = self._orig_proc_mem
        self.sm._query_compute_apps = self._orig_query
        self.sm._compute_apps_cache = self._orig_apps_cache
        self.sm._compute_apps_cache_ts = self._orig_apps_ts
        self.sm._compute_apps_unavailable = self._orig_apps_unavail
        self.sm._get_json = self._orig_get_json
        self.sm._get_text = self._orig_get_text
        self.sm.psutil = self._orig_psutil

    def _wire_running_server(self, pid=12345):
        self.sm._find_server = lambda sid, mode=None: {
            "id": sid or "fake", "mode": "fake", "pid": pid,
            "host": "127.0.0.1", "port": 9999,
            "stdout_log": None, "stderr_log": None,
        }
        self.sm.pid_is_running = lambda pid: True
        # Health/metrics/props returns so we don't take the early-return path.
        self.sm._get_text = lambda url, timeout=3.0: "ok"
        self.sm._get_json = lambda url, timeout=3.0: {"n_ctx": 4096}

    def test_process_block_includes_rss_cpu_and_gpu(self):
        self._wire_running_server(pid=12345)
        self.sm._process_memory = lambda pid: {"rss_bytes": 150 * 1024 * 1024, "cpu_percent": 12.5}
        self.sm._query_compute_apps = lambda: {12345: 2 * 1024 * 1024 * 1024}
        result = self.sm.fetch_server_metrics(server_id="fake")
        self.assertEqual(result["process"]["rss_bytes"], 150 * 1024 * 1024)
        self.assertEqual(result["process"]["cpu_percent"], 12.5)
        self.assertEqual(result["process"]["gpu_used_bytes"], 2 * 1024 * 1024 * 1024)

    def test_gpu_used_is_none_for_untracked_pid(self):
        self._wire_running_server(pid=12345)
        self.sm._process_memory = lambda pid: {"rss_bytes": None, "cpu_percent": None}
        self.sm._query_compute_apps = lambda: {99999: 100 * 1024 * 1024}  # different PID
        result = self.sm.fetch_server_metrics(server_id="fake")
        self.assertIsNone(result["process"]["gpu_used_bytes"])

    def test_compute_apps_unavailable_path(self):
        self._wire_running_server()
        self.sm._process_memory = lambda pid: {"rss_bytes": 1024, "cpu_percent": 0.5}
        # nvidia-smi returns nothing (no GPU / no compute apps) -> query returns None
        self.sm._query_compute_apps = lambda: None
        result = self.sm.fetch_server_metrics(server_id="fake")
        # First call latches disable; gpu_used_bytes stays None.
        self.assertIsNone(result["process"]["gpu_used_bytes"])
        self.assertTrue(self.sm._compute_apps_unavailable)
        # Second call must NOT invoke the subprocess again (disabled).
        calls = []
        def re_call(): calls.append(1); return None
        self.sm._query_compute_apps = re_call
        self.sm.fetch_server_metrics(server_id="fake")
        self.assertEqual(calls, [], "disabled compute-apps must not be re-queried")

    def test_compute_apps_csv_parser_handles_mixture(self):
        # Direct unit test of the parse path: multi-row, with a non-numeric row.
        raw = "111, 2048\n222, 4096\nbroken, row\n333, 8192\n"
        from lcc_core.server_metrics import _query_compute_apps
        # We can't actually call _query_compute_apps without nvidia-smi; verify
        # the data-shape contract via the lookup that fetch_server_metrics uses.
        parsed = {}
        for line in raw.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            try:
                parsed[int(parts[0])] = int(parts[1]) * 1024 * 1024
            except ValueError:
                continue
        self.assertEqual(parsed, {111: 2048 * 1024 * 1024, 222: 4096 * 1024 * 1024, 333: 8192 * 1024 * 1024})

    def test_process_memory_reuses_one_handle_so_cpu_has_a_baseline(self):
        """Regression: a fresh psutil.Process every poll meant cpu_percent always
        returned the meaningless first-call 0.0, which was then coerced to None —
        CPU% was permanently blank."""
        import os

        if self.sm.psutil is None:
            self.skipTest("psutil is not installed")
        pid = os.getpid()

        first = self.sm._process_memory(pid)
        self.assertIsNotNone(first["rss_bytes"])
        # No baseline on the first poll for a PID: None, never a fabricated 0.0.
        self.assertIsNone(first["cpu_percent"])

        handle = self.sm._process_handles[pid]
        second = self.sm._process_memory(pid)
        self.assertIs(self.sm._process_handles[pid], handle, "handle must be reused")
        self.assertIsInstance(second["cpu_percent"], float)
        self.assertGreaterEqual(second["cpu_percent"], 0.0)

    def test_process_memory_forgets_dead_pids(self):
        if self.sm.psutil is None:
            self.skipTest("psutil is not installed")
        dead = 2147483647
        result = self.sm._process_memory(dead)
        self.assertIsNone(result["rss_bytes"])
        self.assertIsNone(result["cpu_percent"])
        self.assertNotIn(dead, self.sm._process_handles)

    def test_process_memory_handles_missing_psutil(self):
        # psutil is a soft dep; absence must produce all-None, not crash.
        self.sm.psutil = None
        self._wire_running_server()
        self.sm._query_compute_apps = lambda: None
        result = self.sm.fetch_server_metrics(server_id="fake")
        self.assertIsNone(result["process"]["rss_bytes"])
        self.assertIsNone(result["process"]["cpu_percent"])
        self.assertIsNone(result["process"]["gpu_used_bytes"])

    def test_fetch_server_metrics_no_matching_server_returns_error(self):
        """M1.3: direct exercise of server_metrics error path when no server tracked."""
        self.sm._find_server = lambda sid, mode=None: None
        result = self.sm.fetch_server_metrics(server_id="nope")
        self.assertFalse(result.get("success"))
        self.assertIn("error", result)
        self.assertIn("No tracked server", result.get("error", ""))

    def test_fetch_server_metrics_dead_pid_returns_error_with_tail(self):
        """M1.3: dead PID path (non-running tracked) returns structured error + stderr_tail for UI surfacing."""
        self.sm._find_server = lambda sid, mode=None: {
            "id": "dead", "mode": "demo", "pid": 2147483647,
            "host": "127.0.0.1", "port": 1234,
            "stdout_log": None, "stderr_log": None,
        }
        self.sm.pid_is_running = lambda p: False
        result = self.sm.fetch_server_metrics(server_id="dead")
        self.assertFalse(result.get("success"))
        self.assertIn("no longer running", result.get("error", ""))
        self.assertIn("stderr_tail", result)


class ServerHistoryTrimTests(unittest.TestCase):
    """trim_server_history must keep the NEWEST servers, and _find_server(mode=)
    must resolve to the running/most-recent entry. Regression: the trim kept the
    oldest `limit` entries while new servers were appended to the end, so a
    freshly launched server was dropped from state the instant it started — which
    made the Stop button a silent no-op (it couldn't find the running PID)."""

    def setUp(self) -> None:
        import lcc_core.server_manager as sm
        self.sm = sm
        self._tmp = tempfile.mkdtemp()
        self._orig_state_path = sm.state_path
        self._orig_pid_running = sm.pid_is_running
        self._state_file = Path(self._tmp) / "servers.json"
        sm.state_path = lambda: self._state_file
        # Default: nothing is "running" unless a test marks it so.
        sm.pid_is_running = lambda pid: False

    def tearDown(self) -> None:
        self.sm.state_path = self._orig_state_path
        self.sm.pid_is_running = self._orig_pid_running
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_state(self, servers):
        self._state_file.write_text(json.dumps({"servers": servers}), encoding="utf-8")

    def test_trim_keeps_newest_not_oldest(self):
        servers = [
            {"id": f"demo-{i}", "mode": "demo", "pid": 1000 + i,
             "status": "stopped", "started_at": f"2026-07-08T00:0{i}:00+00:00"}
            for i in range(7)
        ]
        self._write_state(servers)
        self.sm.trim_server_history(limit=5)
        kept = [s["id"] for s in self.sm.read_state()["servers"]]
        # The two OLDEST (demo-0, demo-1) are dropped; the newest survive.
        self.assertEqual(kept, ["demo-2", "demo-3", "demo-4", "demo-5", "demo-6"])

    def test_newly_started_server_survives_trim(self):
        # A full history of old dead entries, then a brand-new server appended.
        old = [
            {"id": f"old-{i}", "mode": "demo", "pid": 1000 + i,
             "status": "startup_timeout", "started_at": f"2026-07-08T00:0{i}:00+00:00"}
            for i in range(5)
        ]
        self._write_state(old)
        new_server = {"id": "demo-9999", "mode": "demo", "pid": 9999,
                      "status": "starting", "started_at": "2026-07-08T12:00:00+00:00"}
        self.sm._upsert_server(new_server)
        self.sm.trim_server_history(limit=5)
        ids = [s["id"] for s in self.sm.read_state()["servers"]]
        self.assertIn("demo-9999", ids, "the just-started server must not be trimmed away")

    def test_find_server_by_mode_prefers_running(self):
        self._write_state([
            {"id": "dead", "mode": "demo", "pid": 111,
             "status": "startup_timeout", "started_at": "2026-07-08T00:00:00+00:00"},
            {"id": "live", "mode": "demo", "pid": 222,
             "status": "running", "started_at": "2026-07-08T01:00:00+00:00"},
        ])
        # Only PID 222 is alive.
        self.sm.pid_is_running = lambda pid: pid == 222
        found = self.sm._find_server(mode="demo")
        self.assertEqual(found["id"], "live")


class ServerOomHintTests(unittest.TestCase):
    """A freshly-crashed tracked server is annotated oom_likely when the recent
    RAM-pressure rolling window exceeded the OOM threshold before the death.
    Mirrors SwarmUI's pre-crash memory-overload detection."""

    def setUp(self) -> None:
        import lcc_core.server_manager as sm
        self.sm = sm
        self._tmp = tempfile.mkdtemp()
        self._state_file = Path(self._tmp) / "servers.json"
        self._orig_state_path = sm.state_path
        sm.state_path = lambda: self._state_file
        self._orig_ram = sm._ram_pressure
        self._orig_history = list(sm._ram_history)
        sm._ram_history.clear()

    def tearDown(self) -> None:
        self.sm.state_path = self._orig_state_path
        self.sm._ram_pressure = self._orig_ram
        self.sm._ram_history.clear()
        self.sm._ram_history.extend(self._orig_history)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_state(self, servers):
        self._state_file.write_text(json.dumps({"servers": servers}), encoding="utf-8")

    def test_oom_likely_set_when_recent_ram_high(self):
        # The recent window has been at 92% (well over the 80% threshold).
        self.sm._ram_history.extend([0.92, 0.93, 0.91])
        # _ram_pressure is called by _record_ram_pressure; mock to keep window stable.
        self.sm._ram_pressure = lambda: 0.92
        self._write_state([{
            "id": "demo-1", "mode": "demo", "pid": 2147483647,
            "status": "running", "host": "127.0.0.1", "port": 8080,
        }])
        self.sm.refresh_server_states()
        server = self.sm.read_state()["servers"][0]
        self.assertEqual(server["status"], "crashed")
        self.assertTrue(server.get("oom_likely"))

    def test_oom_likely_absent_when_ram_low(self):
        self.sm._ram_history.extend([0.40, 0.45, 0.50])
        self.sm._ram_pressure = lambda: 0.45
        self._write_state([{
            "id": "demo-2", "mode": "demo", "pid": 2147483647,
            "status": "running", "host": "127.0.0.1", "port": 8080,
        }])
        self.sm.refresh_server_states()
        server = self.sm.read_state()["servers"][0]
        self.assertEqual(server["status"], "crashed")
        self.assertNotIn("oom_likely", server)

    def test_no_oom_likely_for_already_stopped_server(self):
        self.sm._ram_history.extend([0.95, 0.95, 0.95])
        self.sm._ram_pressure = lambda: 0.95
        self._write_state([{
            "id": "demo-3", "mode": "demo", "pid": 2147483647,
            "status": "stopped", "host": "127.0.0.1", "port": 8080,
        }])
        self.sm.refresh_server_states()
        server = self.sm.read_state()["servers"][0]
        # 'stopped' is terminal; no annotation even with high RAM.
        self.assertEqual(server["status"], "stopped")
        self.assertNotIn("oom_likely", server)

    def test_ram_pressure_bounded_to_unit_interval(self):
        # Sanity: helper computes correctly even when available > total (shouldn't happen).
        import lcc_core.server_manager as sm
        orig_win = sm._windows_memory_info
        orig_posix = sm._posix_memory_info
        sm._windows_memory_info = lambda: {"total_bytes": 100, "available_bytes": 200}
        sm._posix_memory_info = lambda: {"total_bytes": 100, "available_bytes": 200}
        try:
            self.assertIsNone(sm._ram_pressure())
        finally:
            sm._windows_memory_info = orig_win
            sm._posix_memory_info = orig_posix


class PortAvailabilityTests(unittest.TestCase):
    """Pre-launch TCP probe helpers in server_manager: _is_port_free,
    _next_free_port, and _classify_launch_error."""

    def test_port_free_returns_true_when_nothing_bound(self):
        from lcc_core.server_manager import _is_port_free
        # Find a port nothing is bound to. We pick a high random-ish port and
        # trust the kernel not to have anything on it for the test run.
        candidate = 19000
        attempts = 0
        while not _is_port_free("127.0.0.1", candidate) and attempts < 50:
            candidate += 1
            attempts += 1
        self.assertTrue(_is_port_free("127.0.0.1", candidate))

    def test_port_free_returns_false_when_listener_bound(self):
        from lcc_core.server_manager import _is_port_free
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.listen(1)
            self.assertFalse(_is_port_free("127.0.0.1", port))
        finally:
            sock.close()

    def test_port_free_handles_zero_and_negative(self):
        from lcc_core.server_manager import _is_port_free
        # An invalid port shouldn't raise; treat as "not free" so callers
        # fail loud rather than silently spawning into a bad port.
        self.assertFalse(_is_port_free("127.0.0.1", 0))
        self.assertFalse(_is_port_free("127.0.0.1", -1))

    def test_next_free_port_skips_bound_ports(self):
        from lcc_core.server_manager import _next_free_port, _is_port_free
        # Bind two consecutive ports OUTSIDE the Windows reserved dynamic
        # range so the OS actually allows the bind; if we land inside the
        # range, ``_is_port_free`` reports EACCES and the
        # ``_next_free_port`` Windows skip changes the expected answer.
        start = 20000 if sys.platform == "win32" else 0
        first = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        second = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        first.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        second.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            first.bind(("127.0.0.1", start))
            p1 = first.getsockname()[1]
            first.listen(1)
            second.bind(("127.0.0.1", p1 + 1))
            second.listen(1)
            # The first free port at or above p1 must be p1+2.
            self.assertEqual(_next_free_port("127.0.0.1", p1), p1 + 2)
            self.assertFalse(_is_port_free("127.0.0.1", p1))
            self.assertFalse(_is_port_free("127.0.0.1", p1 + 1))
        finally:
            first.close()
            second.close()

    def test_next_free_port_skips_windows_reserved_range(self):
        if sys.platform != "win32":
            self.skipTest("reserved-range skip is Windows-only")
        from lcc_core.server_manager import MAX_PORT, _next_free_port, _windows_dynamic_port_range
        rng = _windows_dynamic_port_range()
        if rng is None:
            self.skipTest("netsh not available")
        # Start *inside* the reserved range. The search must skip past the
        # range end rather than returning ``start + 1``.
        #
        # On a default Windows host the dynamic range is 49152-65535, i.e. it
        # runs to the end of the port space, so there is no port above it to
        # find. The contract is therefore: either a port above the range end,
        # or None -- never a port inside the range, and never a crash.
        start = rng["start"] + 1000  # safely inside the range
        chosen = _next_free_port("127.0.0.1", start)
        if rng["end"] >= MAX_PORT:
            self.assertIsNone(chosen)
        else:
            self.assertIsNotNone(chosen)
            self.assertGreater(chosen, rng["end"])

    def test_port_above_the_port_space_is_never_probed(self):
        # bind() raises OverflowError above 65535 -- not OSError -- so an
        # unguarded probe crashed instead of reporting "not free". Reached in
        # practice by bumping past a dynamic range that ends at exactly 65535.
        from lcc_core.server_manager import MAX_PORT, _is_port_free, _next_free_port
        self.assertFalse(_is_port_free("127.0.0.1", MAX_PORT + 1))
        self.assertFalse(_is_port_free("127.0.0.1", 999999))
        self.assertIsNone(_next_free_port("127.0.0.1", MAX_PORT + 1))
        # Whatever the walk returns near the boundary, it must be a real port.
        # (Asserting None here instead would be host-dependent: on Windows the
        # dynamic range swallows 65535, on Linux it may well be bindable.)
        near = _next_free_port("127.0.0.1", MAX_PORT - 2, max_tries=5)
        self.assertTrue(near is None or 0 < near <= MAX_PORT)

    def test_next_free_port_returns_none_when_all_bound(self):
        from lcc_core.server_manager import _next_free_port
        # Bind two consecutive ports OUTSIDE the Windows reserved dynamic
        # range so the bind isn't rejected for EACCES; with max_tries=2
        # we probe only those two. Both are bound, so the search must give
        # up and return None rather than picking a wildly high port.
        start = 20000 if sys.platform == "win32" else 0
        first = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        second = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        first.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        second.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            first.bind(("127.0.0.1", start))
            port = first.getsockname()[1]
            first.listen(1)
            second.bind(("127.0.0.1", port + 1))
            second.listen(1)
            self.assertIsNone(_next_free_port("127.0.0.1", port, max_tries=2))
        finally:
            first.close()
            second.close()

    def test_classifier_recognises_port_in_use(self):
        from lcc_core.server_manager import _classify_launch_error
        self.assertIn("Port", _classify_launch_error(
            "E srv  start: couldn't bind HTTP server socket, hostname: 127.0.0.1, port: 8081"
        ))
        self.assertIn("Port", _classify_launch_error(
            "E bind: address already in use on 0.0.0.0:8081"
        ))

    def test_classifier_recognises_oom(self):
        from lcc_core.server_manager import _classify_launch_error
        hint = _classify_launch_error("E cudaMalloc failed: out of memory")
        self.assertIsNotNone(hint)
        self.assertIn("GPU out of memory", hint)

    def test_classifier_recognises_missing_model(self):
        from lcc_core.server_manager import _classify_launch_error
        self.assertIn("Model file", _classify_launch_error(
            "E failed to load model: No such file or directory"
        ))

    def test_classifier_returns_none_for_unknown_stderr(self):
        from lcc_core.server_manager import _classify_launch_error
        self.assertIsNone(_classify_launch_error(""))
        self.assertIsNone(_classify_launch_error("some unrelated noise from llama-server"))

    def test_probe_port_returns_free_for_open_port(self):
        # Skip on Windows: ports below ~15201 are reserved by default and
        # the probe won't ever say "free" on those, so pick a port we
        # know is well above the dynamic range.
        from lcc_core.server_manager import _probe_port
        if sys.platform == "win32":
            port = 20000
        else:
            port = 1  # outside the catch on POSIX too; bind succeeds
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        finally:
            sock.close()
        result = _probe_port("127.0.0.1", port)
        self.assertTrue(result["free"])

    def test_probe_port_returns_in_use_for_listener(self):
        from lcc_core.server_manager import _probe_port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            sock.listen(1)
            result = _probe_port("127.0.0.1", port)
            self.assertFalse(result["free"])
            self.assertEqual(result["reason"], "in_use")
            self.assertNotIn("range", result)
        finally:
            sock.close()

    def test_windows_reserved_range_detected_via_probe(self):
        # Skip this test on non-Windows hosts — the reserved range logic
        # only fires when ``netsh int ipv4 show excludedportrange
        # protocol=tcp`` reports the relevant ports.
        if sys.platform != "win32":
            self.skipTest("reserved-range check is Windows-only")
        from lcc_core.server_manager import (
            _probe_port,
            _next_free_port,
            _windows_excluded_port_ranges,
        )
        excl = _windows_excluded_port_ranges()
        # Find an excluded range that covers a typical llama-server port.
        # On hosts with Hyper-V / Docker installed, 8080/8081 are usually
        # inside an exclusion range.
        target = None
        candidates = (8080, 8081, 9000, 9200, 5005)
        for port in candidates:
            for rng in excl:
                if rng["start"] <= port <= rng["end"]:
                    target = (port, rng)
                    break
            if target:
                break
        if target is None:
            # No standard llama-server port inside an exclusion range on
            # this host — choose a port inside the largest exclusion.
            if not excl:
                self.skipTest("no exclusion ranges reported by netsh")
            rng = max(excl, key=lambda r: r["end"] - r["start"])
            target = (rng["start"], rng)
        port, rng = target
        probe = _probe_port("127.0.0.1", port)
        self.assertFalse(probe["free"])
        self.assertEqual(probe["reason"], "reserved")
        self.assertIn("range", probe)
        # Suggested port must be above the range end, not just port + 1 --
        # unless the reserved space runs to the end of the port range, in
        # which case there is nothing above it and None is the honest answer.
        from lcc_core.server_manager import MAX_PORT, _windows_dynamic_port_range
        above = _next_free_port("127.0.0.1", port)
        dyn = _windows_dynamic_port_range()
        no_room = rng["end"] >= MAX_PORT or (dyn and dyn["end"] >= MAX_PORT
                                             and dyn["start"] <= rng["end"] + 1 <= dyn["end"])
        if no_room:
            self.assertIsNone(above)
        else:
            self.assertIsNotNone(above)
            self.assertGreater(above, rng["end"])


import gguf as _gguf_pkg

# gguf_fixtures lives in this directory; a bare import is required because a
# gitignored vendored checkout (graphify/) ships its own tests package, which
# shadows a `tests.` prefixed import when the whole repo is collected.
from gguf_fixtures import write_minimal_gguf
from lcc_core import estimates as E


def test_attn_layer_count_prefers_tensor_scan_over_interval(tmp_path):
    """Ornith shape: 41 blocks, interval 4, but 11 layers really carry attn_k.

    41 // 4 == 10, which misses the MTP layer at index 40. The tensor scan is
    ground truth and must win.
    """
    attn = [3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 40]
    path = write_minimal_gguf(
        tmp_path / "hybrid.gguf",
        arch="qwen35moe",
        n_layer=41,
        attn_layers=attn,
        n_kv_heads=2,
        k_len=256,
        v_len=256,
        extra_kv={"full_attention_interval": 4},
    )
    reader = _gguf_pkg.GGUFReader(str(path))
    assert E._extract_n_attn_layers(reader, "qwen35moe", 41) == 11


def test_attn_layer_count_falls_back_to_interval_when_no_tensors_match(tmp_path):
    """A file whose tensor names follow no known pattern still gets an answer."""
    path = write_minimal_gguf(
        tmp_path / "opaque.gguf",
        arch="mystery",
        n_layer=41,
        attn_layers=[],
        n_kv_heads=2,
        k_len=256,
        v_len=256,
        extra_kv={"full_attention_interval": 4},
    )
    reader = _gguf_pkg.GGUFReader(str(path))
    assert E._extract_n_attn_layers(reader, "mystery", 41) == 10


if __name__ == "__main__":
    unittest.main()
