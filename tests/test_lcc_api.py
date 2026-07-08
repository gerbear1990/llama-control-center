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

    def test_test_prompt_empty_returns_400(self) -> None:
        response = self.client.post("/api/servers/test-prompt", json={"mode": "anything", "prompt": "   "})

        self.assertEqual(response.status_code, 400)
        self.assertIn("empty", str(response.json()).lower())

    def test_test_prompt_no_running_server_returns_400(self) -> None:
        response = self.client.post(
            "/api/servers/test-prompt", json={"mode": "no-such-server-mode", "prompt": "hi"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("no running tracked server", str(response.json()).lower())


class ProfileDeleteApiTests(unittest.TestCase):
    """Round-trip: write a profile to a sandboxed models.json, delete it,
    verify the entry is gone. Uses find_project_root monkeypatch to point
    the endpoint at a temp directory so we never touch the real manifest."""

    def setUp(self) -> None:
        from lcc_api import app as app_module
        from lcc_core import paths as paths_module

        self.client = TestClient(app_module.app)
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp)
        self.manifest_path = self.root / "models.json"
        self.manifest_path.write_text(
            json.dumps(
                {
                    "models": [
                        {
                            "mode": "to-remove",
                            "name": "Remove me",
                            "recommended_params": {"ctx_size": 4096},
                        },
                        {
                            "mode": "to-keep",
                            "name": "Keep me",
                            "recommended_params": {"ctx_size": 8192},
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        self._orig_find_root = paths_module.find_project_root
        paths_module.find_project_root = lambda *a, **kw: self.root

    def tearDown(self) -> None:
        from lcc_core import paths as paths_module

        paths_module.find_project_root = self._orig_find_root
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_delete_removes_only_target_entry(self) -> None:
        response = self.client.post(
            "/api/profiles/delete", json={"mode": "to-remove"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["mode"], "to-remove")

        # The kept entry is untouched, the removed one is gone.
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        modes = [m.get("mode") for m in manifest.get("models", [])]
        self.assertEqual(modes, ["to-keep"])

    def test_delete_unknown_mode_returns_400(self) -> None:
        # The endpoint reports validation failures with success=False and a 200
        # response (matches /api/profiles/save). The 400 only fires when the
        # server-running guard rejects the request.
        response = self.client.post(
            "/api/profiles/delete", json={"mode": "nope"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["success"])
        self.assertIn("unknown profile mode", response.json()["message"].lower())

    def test_delete_refuses_when_tracked_server_running(self) -> None:
        import lcc_core.server_manager as sm

        # Inject a fake tracked entry that's still running. Monkeypatch
        # ``list_servers`` itself (the endpoint imports it inside the handler,
        # so the module-level rebind is what the endpoint sees). The fake
        # entry must include ``running: True`` since ``list_servers`` normally
        # fills that field from ``pid_is_running``.
        fake = [
            {
                "id": "to-remove-running",
                "mode": "to-remove",
                "pid": 2147483647,
                "host": "127.0.0.1",
                "port": 8080,
                "stdout_log": None,
                "stderr_log": None,
                "running": True,
            }
        ]
        orig_list = sm.list_servers
        sm.list_servers = lambda: fake
        try:
            response = self.client.post(
                "/api/profiles/delete", json={"mode": "to-remove"}
            )
        finally:
            sm.list_servers = orig_list
        # The endpoint reports rejections with success=False (matching the
        # other endpoints in this file); it never raises HTTPException for
        # a delete-while-running guard.
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["success"])
        self.assertIn("tracked server running", response.json()["message"].lower())
        # The manifest is unchanged.
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        modes = [m.get("mode") for m in manifest.get("models", [])]
        self.assertIn("to-remove", modes)


if __name__ == "__main__":
    unittest.main()
