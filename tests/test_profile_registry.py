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


if __name__ == "__main__":
    unittest.main()
