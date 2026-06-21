from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from lcc_core.config import AppConfig
from lcc_core.estimates import estimate_memory_fit, estimate_tokens_per_second
from lcc_core.fit import apply_fit_suggestions, build_fit_args, parse_fit_output
from lcc_core.hf_metadata import infer_query
from lcc_core.inventory import build_inventory
from lcc_core.llama_args import build_llama_server_args
from lcc_core.manifest import load_profiles
from lcc_core.models import discover_models, parse_params, parse_quant
from lcc_core.paths import find_project_root
from lcc_core.portability import scan_portability_issues
from lcc_core.profile_resolver import resolve_profiles


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


class ManifestTests(unittest.TestCase):
    def test_manifest_profiles_flag_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_path = root / "models" / "portable.gguf"
            model_path.parent.mkdir()
            model_path.write_bytes(b"gguf")
            script = root / "start-portable.ps1"
            script.write_text("$model = 'C:\\Users\\someone\\models\\portable.gguf'\n", encoding="utf-8")
            manifest = {
                "models": [
                    {
                        "mode": "portable",
                        "name": "Portable",
                        "script": script.name,
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

    def test_find_project_root_uses_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "a" / "b"
            child.mkdir(parents=True)
            (root / "models.json").write_text('{"models": []}', encoding="utf-8")

            self.assertEqual(find_project_root(child), root)


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


class LaunchArgsTests(unittest.TestCase):
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
        self.assertIn("--spec-type", cmd.argv)
        self.assertIn("--spec-draft-n-max", cmd.argv)
        self.assertIn("--temp", cmd.argv)
        self.assertIn("0.7", cmd.argv)
        self.assertIn("--top-p", cmd.argv)
        self.assertIn("--repeat-penalty", cmd.argv)
        self.assertIn("--predict", cmd.argv)
        self.assertIn("--no-kv-offload", cmd.argv)
        self.assertIn("--no-op-offload", cmd.argv)

    def test_string_gpu_layers_do_not_crash(self) -> None:
        # 'all'/'auto' and float-ish strings are valid manifest values elsewhere
        # in the app; the arg builders must not raise on them.
        for value, expected in [("all", "all"), ("auto", "all"), ("32.0", "32"), (24, "24")]:
            cmd = build_llama_server_args("llama-server", "m.gguf", {"gpu_layers": value})
            self.assertIn("--gpu-layers", cmd.argv)
            self.assertEqual(cmd.argv[cmd.argv.index("--gpu-layers") + 1], expected)
        fit = build_fit_args("llama-fit-params", "m.gguf", {"gpu_layers": "all"})
        self.assertEqual(fit[fit.index("-ngl") + 1], "-2")

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
        parsed = parse_fit_output("-c 262144 -ngl -2\n", "CUDA0 22201 2879 814")
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
            "CUDA0 26090 1803 826\nprojected to use 28719 MiB on CUDA0 vs. 32606 MiB free",
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


if __name__ == "__main__":
    unittest.main()
