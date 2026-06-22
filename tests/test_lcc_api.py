from __future__ import annotations

import json
import tempfile
import unittest
import warnings
from pathlib import Path

try:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated.*")
        from fastapi.testclient import TestClient

    from lcc_api.app import app
except ImportError as exc:  # fastapi/httpx are optional test deps; skip rather than error.
    raise unittest.SkipTest(f"API smoke tests need fastapi + httpx installed: {exc}")


class ApiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health_config_and_servers(self) -> None:
        index = self.client.get("/")
        self.assertEqual(index.status_code, 200)
        self.assertIn("Llama Control Center", index.text)
        css = self.client.get("/static/styles.css")
        self.assertEqual(css.status_code, 200)
        self.assertIn("--accent", css.text)
        self.assertEqual(self.client.get("/health").json(), {"ok": True})
        meta = self.client.get("/api/meta")
        self.assertEqual(meta.status_code, 200)
        self.assertIn("version", meta.json())
        self.assertIn("name", meta.json())
        config = self.client.get("/api/config")
        self.assertEqual(config.status_code, 200)
        self.assertEqual(config.json()["default_backend"], "llama.cpp")
        self.assertEqual(config.json()["update_channel"], "stable")
        self.assertIn("runtime_dirs", config.json())
        servers = self.client.get("/api/servers")
        self.assertEqual(servers.status_code, 200)
        self.assertIn("servers", servers.json())
        system = self.client.get("/api/system")
        self.assertEqual(system.status_code, 200)
        self.assertIn("cpu", system.json())

    def test_runtime_updates_endpoint_shape(self) -> None:
        response = self.client.get("/api/runtime-updates")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("channel", payload)
        self.assertIn("checked_at", payload)
        self.assertIn("updates", payload)
        self.assertIn("supported_channels", payload)
        for entry in payload["updates"]:
            self.assertIn("runtime_id", entry)
            self.assertIn("current_version", entry)
            self.assertIn("latest_version", entry)
            self.assertIn("update_available", entry)
            self.assertIsInstance(entry["update_available"], bool)

        refresh = self.client.post("/api/runtime-updates/refresh")
        self.assertEqual(refresh.status_code, 200)
        self.assertEqual(refresh.json()["channel"], payload["channel"])

    def test_profiles_can_use_explicit_project_root_and_model_dir(self) -> None:
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

            response = self.client.post(
                "/api/profiles",
                json={"project_root": str(root), "model_dirs": [str(model_dir)]},
            )
            estimate = self.client.post(
                "/api/estimate/tokens-per-second",
                json={"mode": "tiny", "project_root": str(root), "model_dirs": [str(model_dir)], "overrides": {}},
            )
            launch_estimate = self.client.post(
                "/api/estimate/launch",
                json={"mode": "tiny", "project_root": str(root), "model_dirs": [str(model_dir)], "overrides": {}},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["summary"]["launchable_profile_count"], 1)
        self.assertEqual(payload["resolved_profiles"][0]["mode"], "tiny")
        self.assertIn("fit_status", payload["resolved_profiles"][0])
        self.assertEqual(estimate.status_code, 200)
        self.assertGreater(estimate.json()["estimate"]["estimate_tps"], 0)
        self.assertEqual(launch_estimate.status_code, 200)
        self.assertIn("fit_status", launch_estimate.json())
        self.assertIn("speed_estimate", launch_estimate.json())

    def test_prepare_unknown_profile_returns_400(self) -> None:
        response = self.client.post("/api/servers/prepare", json={"mode": "missing"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("Unknown profile mode", str(response.json()))

    def test_hf_info_bad_query_returns_404(self) -> None:
        response = self.client.post("/api/models/hf-info", json={"repo_id": "this/repo-should-not-exist-000000"})

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
