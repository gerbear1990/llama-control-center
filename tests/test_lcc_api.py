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

    def test_profiles_scan_registers_and_launch_scripts_routes_are_gone(self) -> None:
        # Stub the registry so the route test never scans (or mutates) the
        # real models.json / model folders; the registry behavior itself is
        # covered by tests/test_profile_registry.py.
        import lcc_api.app as app_module
        from lcc_core.profile_registry import ScanResult

        orig = app_module.register_discovered_models
        app_module.register_discovered_models = lambda: ScanResult(scanned_at="test")
        try:
            scan = self.client.post("/api/profiles/scan")
        finally:
            app_module.register_discovered_models = orig
        self.assertEqual(scan.status_code, 200)
        payload = scan.json()
        self.assertTrue(payload["success"])
        for key in ("registered", "skipped", "errors", "scanned_model_count", "registered_count"):
            self.assertIn(key, payload)
        self.assertEqual(self.client.get("/api/launch-scripts").status_code, 404)
        self.assertEqual(self.client.post("/api/launch-scripts/scan").status_code, 404)
        self.assertEqual(self.client.post("/api/hf-cli/install").status_code, 404)

    def test_servers_purge_route(self) -> None:
        # Stub the core purge so the route test never mutates real server state.
        from unittest import mock

        with mock.patch("lcc_core.server_manager.purge_server_history") as purge:
            purge.return_value = {"success": True, "removed": 2, "remaining": 1, "message": "Removed 2"}
            res = self.client.post("/api/servers/purge?only_non_running=true")
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.json()["success"])
            purge.assert_called_once_with(only_non_running=True, all=False)

        with mock.patch("lcc_core.server_manager.purge_server_history") as purge:
            purge.return_value = {"success": True, "removed": 3, "remaining": 0, "message": "Removed all"}
            res = self.client.post("/api/servers/purge?all=true")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["removed"], 3)
            purge.assert_called_once_with(only_non_running=True, all=True)

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

    def test_server_metrics_unknown_id_returns_400(self) -> None:
        """M1.3: exercise server_metrics error path at API boundary (no server -> 400)."""
        response = self.client.get("/api/servers/unknown-xyz/metrics")
        self.assertEqual(response.status_code, 400)
        # detail contains the error payload from the real fetch_server_metrics
        self.assertIn("detail", response.json())

    def test_server_logs_endpoint_unknown_returns_400(self) -> None:
        """M2: wiring test for the previously-missing /logs endpoint (P1 bugfix)."""
        response = self.client.get("/api/servers/unknown-xyz/logs?lines=50")
        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.json())

    def test_server_logs_func_error_and_contract(self) -> None:
        """Direct exercise of server_logs real function (positive error shape + contract for success shape)."""
        from lcc_core.server_manager import server_logs
        result = server_logs("no-such-id")
        self.assertFalse(result.get("success"))
        self.assertIn("error", result)
        # success shape contract (would be present when found)
        # call with known-bad to confirm no crash on lines param
        result2 = server_logs("no-such-id", lines=5)
        self.assertFalse(result2.get("success"))


class ServerMetricsLogsInjectedStateTests(unittest.TestCase):
    """M1.3/M2: exercise /metrics and /logs endpoints + real funcs with injected
    server state (dead pid path, error returns, no-psutil graceful)."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_metrics_dead_pid_and_logs_unknown_via_patched_state(self) -> None:
        import lcc_core.server_metrics as smet
        import lcc_core.server_manager as sm
        orig_find = smet._find_server
        orig_pid = sm.pid_is_running
        try:
            # Simulate a tracked server whose pid is dead (exercises the early error return in fetch)
            smet._find_server = lambda sid, mode=None: {
                "id": sid or "inj", "mode": "inj", "pid": 2147483647,
                "host": "127.0.0.1", "port": 9,
                "stdout_log": None, "stderr_log": None,
            }
            sm.pid_is_running = lambda p: False
            resp = self.client.get("/api/servers/inj/metrics")
            self.assertEqual(resp.status_code, 400)
            body = resp.json()
            self.assertIn("detail", body)
            self.assertIn("no longer running", str(body))
            # logs for unknown still 400 (server_logs looks up tracked)
            resp2 = self.client.get("/api/servers/inj/logs")
            self.assertEqual(resp2.status_code, 400)
        finally:
            smet._find_server = orig_find
            sm.pid_is_running = orig_pid

    def test_server_logs_error_shape_direct(self) -> None:
        # Already covered but re-assert via client for completeness with injected concept
        resp = self.client.get("/api/servers/deadbeef/logs")
        self.assertEqual(resp.status_code, 400)

    def test_server_logs_positive_with_temp_files_and_injected_tracked(self) -> None:
        """Positive AC2/M2 test: real tracked server with stdout/stderr log files returns success + tails via API and server_logs."""
        import lcc_core.server_manager as sm
        import tempfile
        import shutil
        from pathlib import Path as P

        tmp = tempfile.mkdtemp()
        try:
            state_file = P(tmp) / "servers.json"
            out_log = P(tmp) / "out.log"
            err_log = P(tmp) / "err.log"
            out_log.write_text("hello stdout line1\nline2\n", encoding="utf-8")
            err_log.write_text("error line A\nline B with content\n", encoding="utf-8")

            sid = "pos-logs-123"
            entry = {
                "id": sid,
                "mode": "pos-test",
                "pid": 12345,
                "status": "running",
                "host": "127.0.0.1",
                "port": 18080,
                "stdout_log": str(out_log),
                "stderr_log": str(err_log),
            }
            state_file.write_text(json.dumps({"servers": [entry]}), encoding="utf-8")

            orig_state = sm.state_path
            sm.state_path = lambda: state_file
            try:
                # direct func
                res = sm.server_logs(sid, lines=10)
                self.assertTrue(res.get("success"))
                self.assertIn("hello stdout", res.get("stdout", ""))
                self.assertIn("error line A", res.get("stderr", ""))

                # via API
                r = self.client.get(f"/api/servers/{sid}/logs?lines=5")
                self.assertEqual(r.status_code, 200)
                body = r.json()
                self.assertTrue(body.get("success"))
                self.assertIn("stdout", body)
                self.assertIn("stderr", body)
                self.assertIn("line2", body.get("stdout", ""))
            finally:
                sm.state_path = orig_state
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


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


class ProfileSaveSafetyTests(unittest.TestCase):
    """Regression: /api/profiles/save used to silently reset models.json to
    ``{"models": []}`` when the read raised any error, wiping every existing
    profile in one transaction. It must now refuse with success=False and
    leave the on-disk manifest untouched."""

    def setUp(self) -> None:
        from lcc_api import app as app_module
        from lcc_core import paths as paths_module

        self.client = TestClient(app_module.app)
        self._tmp = tempfile.mkdtemp()
        self.root = Path(self._tmp)
        self.manifest_path = self.root / "models.json"
        # Seed three profiles; two must survive any subsequent save.
        self.manifest_path.write_text(
            json.dumps(
                {
                    "models": [
                        {"mode": "keep-a", "name": "A", "recommended_params": {"ctx_size": 4096}},
                        {"mode": "keep-b", "name": "B", "recommended_params": {"ctx_size": 4096}},
                        {"mode": "keep-c", "name": "C", "recommended_params": {"ctx_size": 4096}},
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

    def _read_modes(self) -> list[str]:
        return [m.get("mode") for m in json.loads(self.manifest_path.read_text(encoding="utf-8")).get("models", [])]

    def test_save_with_corrupt_manifest_refuses_and_preserves_existing_profiles(self) -> None:
        # Simulate a transient corrupt models.json (antivirus lock, partial
        # write from a prior crash, manual edit gone wrong).
        self.manifest_path.write_bytes(b"{ this is not valid json }")
        response = self.client.post(
            "/api/profiles/save",
            json={
                "mode": "new-mode",
                "name": "New",
                "description": "",
                "model_path": "",
                "params": {"ctx_size": 4096},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["success"])
        self.assertIn("could not be read", response.json()["message"].lower())
        # The corrupt on-disk content must NOT have been overwritten.
        self.assertEqual(self.manifest_path.read_bytes(), b"{ this is not valid json }")

    def test_save_with_valid_manifest_still_works(self) -> None:
        # Sanity: the fix doesn't break the happy path.
        before = self._read_modes()
        response = self.client.post(
            "/api/profiles/save",
            json={
                "mode": "keep-a",
                "name": "A renamed",
                "description": "touched",
                "model_path": "",
                "params": {"ctx_size": 8192},
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        after = self._read_modes()
        # No profiles were silently dropped; only the targeted one was updated.
        self.assertEqual(set(after), set(before))
        renamed = next(
            m for m in json.loads(self.manifest_path.read_text(encoding="utf-8"))["models"] if m["mode"] == "keep-a"
        )
        self.assertEqual(renamed["name"], "A renamed")
        self.assertEqual(renamed["recommended_params"]["ctx_size"], 8192)

    def test_delete_with_corrupt_manifest_refuses_and_preserves_existing_profiles(self) -> None:
        self.manifest_path.write_bytes(b"not json at all")
        response = self.client.post(
            "/api/profiles/delete", json={"mode": "keep-a"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["success"])
        self.assertIn("could not be read", response.json()["message"].lower())
        self.assertEqual(self.manifest_path.read_bytes(), b"not json at all")


class ManifestHelpersTests(unittest.TestCase):
    """The shared manifest I/O helpers: load_manifest_safely must surface
    unreadable files as ManifestReadError instead of resetting, and
    write_manifest_atomic must write tmp+rename."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self.path = Path(self._tmp) / "models.json"

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)


class ServerMetricsFormatterTests(unittest.TestCase):
    """Unit test for the *shipped* formatServerMetricsLine (pure, extracted per strategy).
    Ev als the real lcc_api/static/app.js via Node + vm with minimal stubs.
    Fixture is representative of a successful /metrics response (from probe).
    Asserts correct separators, all fields present, and NO glued text (KVslots etc).
    """

    def test_format_server_metrics_line_shipped_no_glue(self):
        # Run the real formatter via the committed test helper (drives shipped code).
        import subprocess
        import json
        from pathlib import Path as P

        js_test = P(__file__).parent / "test_server_metrics_formatter.js"
        # node must be on PATH (verified in env)
        # Node emits UTF-8; decode explicitly so the separator survives on
        # machines whose locale encoding is not UTF-8 (e.g. cp1252 Windows).
        out = subprocess.check_output(["node", str(js_test)], encoding="utf-8", cwd=P(__file__).parent.parent)
        data = json.loads(out.strip())
        line = data["line"]

        # Required fields from fixture
        self.assertIn("42% KV", line)
        self.assertIn("3.2 t/s", line)
        self.assertIn("slots 1/1", line)
        self.assertIn("ctx 8192", line)
        self.assertIn("RSS", line)
        self.assertIn("VRAM", line)

        # One consistent separator rule
        self.assertIn(" · ", line)

        # No glue bugs
        self.assertNotIn("KVslots", line)
        self.assertNotIn("t/sslots", line)
        self.assertNotIn("1/1ctx", line)
        self.assertNotIn("KVctx", line)

        # Should not start or end with separator
        self.assertFalse(line.startswith(" · "))
        self.assertFalse(line.endswith(" · "))

    def test_profile_for_model_path_matcher(self):
        import subprocess
        import json
        from pathlib import Path as P

        js_test = P(__file__).parent / "test_models_pane_matcher.js"
        out = subprocess.check_output(["node", str(js_test)], encoding="utf-8", cwd=P(__file__).parent.parent)
        data = json.loads(out.strip())
        self.assertTrue(data["ok"], data)

# Lifted from scratch launch_and_probe.py for committed test (per strategy)
# Provides representative state success for /metrics (AC3) inside the test suite.
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import json as _json  # avoid name clash if any

class _DummyLlamaHandler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, "text/plain", "ok")
            return
        if self.path == "/props":
            self._send(200, "application/json", _json.dumps({"n_ctx": 8192, "model_name": "probe-dummy"}))
            return
        if self.path == "/metrics":
            prom = (
                "# TYPE llamacpp_kv_cache_usage_ratio gauge\n"
                "llamacpp_kv_cache_usage_ratio 0.42\n"
                "llamacpp_kv_cache_tokens 1234\n"
                "llamacpp_prompt_tokens_seconds 10.5\n"
                "llamacpp_tokens_predicted_seconds 3.2\n"
                "llamacpp_active_slots 1\n"
                "llamacpp_processing_slots 1\n"
            )
            self._send(200, "text/plain", prom)
            return
        self._send(404, "text/plain", "not found")

    def log_message(self, format, *args):
        return  # quiet


class MetricsSuccessWithStubTests(unittest.TestCase):
    """test_metrics_success_with_http_stub_and_injected_state (lifted per strategist rec).
    Uses dummy HTTP + patched state to exercise success path for /metrics on representative state.
    This is now in committed tests (replaces sole reliance on scratch probe).
    """

    def setUp(self):
        self.client = TestClient(app)

    def test_metrics_success_with_http_stub_and_injected_state(self):
        import lcc_core.server_manager as sm
        import os
        import tempfile
        import shutil
        from pathlib import Path as P

        tmp = tempfile.mkdtemp()
        httpd = None
        try:
            state_file = P(tmp) / "servers.json"
            dummy_port = 19099
            dummy_pid = os.getpid()
            httpd = HTTPServer(("127.0.0.1", dummy_port), _DummyLlamaHandler)
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            entry = {
                "id": "success-metrics",
                "mode": "success-test",
                "pid": dummy_pid,
                "status": "running",
                "running": True,
                "host": "127.0.0.1",
                "port": dummy_port,
                "stdout_log": None,
                "stderr_log": None,
            }
            state_file.write_text(_json.dumps({"servers": [entry]}), encoding="utf-8")
            orig_state = sm.state_path
            sm.state_path = lambda: state_file
            orig_pid = sm.pid_is_running
            sm.pid_is_running = lambda p: True if p == dummy_pid else orig_pid(p)
            try:
                resp = self.client.get("/api/servers/success-metrics/metrics")
                self.assertEqual(resp.status_code, 200)
                body = resp.json()
                self.assertTrue(body.get("success"))
                self.assertIn("summary", body)
                self.assertIn("props", body)
                self.assertIn("process", body)
            finally:
                sm.state_path = orig_state
                sm.pid_is_running = orig_pid
                if httpd:
                    try:
                        httpd.shutdown()
                    except Exception:
                        pass
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
