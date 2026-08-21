from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from lcc_core.config import AppConfig
from lcc_core.profile_registry import (
    register_discovered_models,
    startup_autoscan_if_enabled,
)


class _IsolatedDirs(unittest.TestCase):
    """Each test gets a fresh config/cache dir + sandboxed project root."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._orig_cwd = os.getcwd()
        self.config_dir = Path(self._tmp) / "config"
        self.cache_dir = Path(self._tmp) / "cache"
        self.config_dir.mkdir(parents=True)
        self.cache_dir.mkdir(parents=True)

        self._orig_env = {
            "LCC_CONFIG_DIR": os.environ.get("LCC_CONFIG_DIR"),
            "LCC_CACHE_DIR": os.environ.get("LCC_CACHE_DIR"),
        }
        os.environ["LCC_CONFIG_DIR"] = str(self.config_dir)
        os.environ["LCC_CACHE_DIR"] = str(self.cache_dir)

        self.project_root = Path(self._tmp) / "project"
        self.project_root.mkdir()
        (self.project_root / "models.json").write_text('{"models": []}', encoding="utf-8")
        self.model_dir = self.project_root / "models"
        self.model_dir.mkdir()
        # Sandbox find_project_root() fallbacks.
        os.chdir(self.project_root)

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        shutil.rmtree(self._tmp, ignore_errors=True)
        for key, value in self._orig_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _seed_model(self, name: str) -> Path:
        path = self.model_dir / name
        path.write_bytes(b"model-bytes")
        return path

    def _manifest(self) -> dict:
        return json.loads((self.project_root / "models.json").read_text(encoding="utf-8"))


class RegisterDiscoveredModelsTests(_IsolatedDirs):
    def test_new_model_is_registered_with_model_path(self) -> None:
        model = self._seed_model("NewModel-7B-Q4_K_M.gguf")
        result = register_discovered_models(project_root=self.project_root, model_dirs=[self.model_dir])
        self.assertEqual(result.errors, [])
        modes = {item.mode for item in result.registered}
        self.assertIn("newmodel-7b-q4_k_m", modes)
        doc = self._manifest()
        entry = next(e for e in doc["models"] if e["mode"] == "newmodel-7b-q4_k_m")
        self.assertEqual(Path(entry["model_path"]).name, model.name)
        self.assertNotIn("script", entry)
        self.assertIn("recommended_params", entry)
        self.assertIn("ctx_size", entry["recommended_params"])

    def test_stale_pin_does_not_swallow_a_new_model(self) -> None:
        """A missing pinned path must not fuzzy-match a similarly named new file.

        That was stealing new GGUFs so they never got their own profile.
        """
        new_model = self._seed_model("Qwen3.8-27B-Heretic-Q4_K_M.gguf")
        (self.project_root / "models.json").write_text(
            json.dumps({"models": [{
                "mode": "huihui-qwable-3.6-27b",
                "name": "Huihui Qwable (gone)",
                "description": "",
                "model_path": str(self.model_dir / "Huihui-Qwable-3.6-27b-abliterated-Q4_K_M.gguf"),
                "recommended_params": {"ctx_size": 4096, "threads": 4, "gpu_layers": 999,
                                       "cache_type_k": "q4_0", "cache_type_v": "q4_0"},
            }]}),
            encoding="utf-8",
        )
        result = register_discovered_models(project_root=self.project_root, model_dirs=[self.model_dir])
        self.assertEqual(result.errors, [])
        self.assertEqual({item.model_path for item in result.registered}, {str(new_model)})
        modes = [entry["mode"] for entry in self._manifest()["models"]]
        self.assertIn("huihui-qwable-3.6-27b", modes)
        self.assertEqual(len(modes), 2)

    def test_nvfp4_mtp_product_name_is_registered(self) -> None:
        model = self._seed_model("Qwen3.8-27B-NVFP4-MTP-Q8attn.gguf")
        result = register_discovered_models(project_root=self.project_root, model_dirs=[self.model_dir])
        self.assertEqual({item.model_path for item in result.registered}, {str(model)})

    def test_mtp_folder_companion_is_still_skipped(self) -> None:
        mtp_dir = self.model_dir / "MTP"
        mtp_dir.mkdir()
        (mtp_dir / "gemma-4-26B-it-Q8_0-MTP.gguf").write_bytes(b"draft")
        result = register_discovered_models(project_root=self.project_root, model_dirs=[self.model_dir])
        self.assertEqual(result.registered, [])
        reasons = " ".join(item["reason"] for item in result.skipped)
        self.assertIn("Draft", reasons)

    def test_only_paths_registers_just_that_file(self) -> None:
        keep = self._seed_model("Keep-7B-Q4_K_M.gguf")
        self._seed_model("Skip-7B-Q4_K_M.gguf")
        result = register_discovered_models(
            project_root=self.project_root,
            model_dirs=[self.model_dir],
            only_paths=[str(keep)],
        )
        self.assertEqual({item.model_path for item in result.registered}, {str(keep)})
        self.assertEqual(len(self._manifest()["models"]), 1)

    def test_existing_profile_model_is_not_reregistered(self) -> None:
        model = self._seed_model("Known-7B-Q4_K_M.gguf")
        (self.project_root / "models.json").write_text(
            json.dumps({"models": [{
                "mode": "known",
                "name": "Known",
                "description": "",
                "model_path": str(model),
                "recommended_params": {"ctx_size": 4096, "threads": 4, "gpu_layers": 999,
                                       "cache_type_k": "q8_0", "cache_type_v": "q8_0"},
            }]}),
            encoding="utf-8",
        )
        result = register_discovered_models(project_root=self.project_root, model_dirs=[self.model_dir])
        self.assertEqual(result.registered, [])
        self.assertEqual(len(self._manifest()["models"]), 1)

    def test_draft_models_are_skipped(self) -> None:
        self._seed_model("Tiny-0.5B-draft-Q8_0.gguf")
        result = register_discovered_models(project_root=self.project_root, model_dirs=[self.model_dir])
        self.assertEqual(result.registered, [])
        reasons = " ".join(item["reason"] for item in result.skipped)
        self.assertIn("Draft", reasons)
        self.assertEqual(self._manifest()["models"], [])

    def test_corrupt_manifest_refuses_to_register(self) -> None:
        self._seed_model("NewModel-7B-Q4_K_M.gguf")
        (self.project_root / "models.json").write_text("{not json", encoding="utf-8")
        result = register_discovered_models(project_root=self.project_root, model_dirs=[self.model_dir])
        self.assertEqual(result.registered, [])
        self.assertTrue(result.errors)
        # File untouched — no silent wipe.
        self.assertEqual((self.project_root / "models.json").read_text(encoding="utf-8"), "{not json")


class IgnoredModelPathTests(_IsolatedDirs):
    """Deleting a profile must stick: the GGUF stays on disk, so the tombstone
    list is the only thing stopping the next scan from re-registering it."""

    def test_ignored_model_is_not_registered(self) -> None:
        model = self._seed_model("Deleted-7B-Q4_K_M.gguf")
        config = AppConfig(model_dirs=[str(self.model_dir)], ignored_model_paths=[str(model)])
        result = register_discovered_models(
            project_root=self.project_root, model_dirs=[self.model_dir], config=config
        )
        self.assertEqual(result.registered, [])
        self.assertEqual(self._manifest()["models"], [])
        reasons = " ".join(item["reason"] for item in result.skipped)
        self.assertIn("deleted by the user", reasons.lower())

    def test_ignored_match_is_case_insensitive(self) -> None:
        model = self._seed_model("Deleted-7B-Q4_K_M.gguf")
        config = AppConfig(model_dirs=[str(self.model_dir)], ignored_model_paths=[str(model).upper()])
        result = register_discovered_models(
            project_root=self.project_root, model_dirs=[self.model_dir], config=config
        )
        self.assertEqual(result.registered, [])

    def test_non_ignored_models_still_register(self) -> None:
        self._seed_model("Deleted-7B-Q4_K_M.gguf")
        keeper = self._seed_model("Keeper-7B-Q4_K_M.gguf")
        config = AppConfig(
            model_dirs=[str(self.model_dir)],
            ignored_model_paths=[str(self.model_dir / "Deleted-7B-Q4_K_M.gguf")],
        )
        result = register_discovered_models(
            project_root=self.project_root, model_dirs=[self.model_dir], config=config
        )
        self.assertEqual({item.model_path for item in result.registered}, {str(keeper)})


class ConfigFieldTests(_IsolatedDirs):
    def test_auto_scan_on_startup_round_trips(self) -> None:
        config = AppConfig(auto_scan_on_startup=False)
        path = config.save(self.config_dir / "config.json")
        loaded = AppConfig.load(path)
        self.assertFalse(loaded.auto_scan_on_startup)

    def test_ignored_model_paths_round_trip(self) -> None:
        config = AppConfig(ignored_model_paths=[r"C:\models\gone.gguf"])
        loaded = AppConfig.load(config.save(self.config_dir / "config.json"))
        self.assertEqual(loaded.ignored_model_paths, [r"C:\models\gone.gguf"])


class StartupAutoscanTests(_IsolatedDirs):
    def test_disabled_when_config_says_so(self) -> None:
        config = AppConfig(auto_scan_on_startup=False)
        self.assertIsNone(startup_autoscan_if_enabled(config))

    def test_runs_when_enabled(self) -> None:
        self._seed_model("NewModel-7B-Q4_K_M.gguf")
        config = AppConfig(auto_scan_on_startup=True, model_dirs=[str(self.model_dir)])
        result = startup_autoscan_if_enabled(config)
        self.assertIsNotNone(result)
        self.assertEqual({item.mode for item in result.registered}, {"newmodel-7b-q4_k_m"})


class PinMatchTests(unittest.TestCase):
    def test_missing_pin_does_not_fuzzy_match(self) -> None:
        from lcc_core.profile_resolver import _best_model
        from lcc_core.schema import ModelFile, ModelProfile

        profile = ModelProfile(
            mode="huihui-qwable",
            name="Huihui Qwable",
            description="",
            model_path=r"C:\models\Huihui-Qwable-3.6-27b-Q4_K_M.gguf",
        )
        candidate = ModelFile(
            id="x",
            name="Qwen3.8-27B-Heretic-Abliterated",
            path=r"C:\models\Qwen3.8-27B-Heretic\RVN-Q4_K_M.gguf",
            source="scan",
            format="GGUF",
            size_bytes=10,
        )
        model, score, warnings = _best_model(profile, [candidate])
        self.assertIsNone(model)
        self.assertEqual(score, 0.0)
        self.assertTrue(any("missing" in warning.lower() for warning in warnings))


if __name__ == "__main__":
    unittest.main()
