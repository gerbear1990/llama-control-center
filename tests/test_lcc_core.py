from __future__ import annotations

import json
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


if __name__ == "__main__":
    unittest.main()
