from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import lcc_core.server_manager as server_manager

_START_LCC = Path(__file__).resolve().parent.parent / "start-lcc.py"


def _load_launcher():
    spec = importlib.util.spec_from_file_location("lcc_launcher_under_test", _START_LCC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StopModelServersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.launcher = _load_launcher()
        self._orig_list = server_manager.list_servers
        self._orig_stop = server_manager.stop_server
        self.stop_calls: list[str] = []

    def tearDown(self) -> None:
        server_manager.list_servers = self._orig_list
        server_manager.stop_server = self._orig_stop

    def test_reaps_each_running_tracked_server(self) -> None:
        server_manager.list_servers = lambda: [
            {"id": "a", "mode": "qwen", "pid": 111, "running": True},
            {"id": "b", "mode": "agent", "pid": 222, "running": True},
            {"id": "c", "mode": "old", "pid": 333, "running": False},  # already dead
            {"id": "d", "mode": "nopid", "pid": None, "running": True},  # no pid
        ]

        def fake_stop(server_id=None, mode=None, timeout=10):
            self.stop_calls.append(server_id)
            return {"success": True, "message": f"stopped {server_id}"}

        server_manager.stop_server = fake_stop
        stopped = self.launcher.stop_model_servers()
        self.assertEqual(stopped, 2)
        self.assertEqual(self.stop_calls, ["a", "b"])

    def test_counts_only_successful_stops(self) -> None:
        server_manager.list_servers = lambda: [
            {"id": "a", "mode": "qwen", "pid": 111, "running": True},
            {"id": "b", "mode": "agent", "pid": 222, "running": True},
        ]

        def fake_stop(server_id=None, mode=None, timeout=10):
            self.stop_calls.append(server_id)
            return {"success": server_id == "a", "message": "nope"}

        server_manager.stop_server = fake_stop
        stopped = self.launcher.stop_model_servers()
        self.assertEqual(stopped, 1)
        self.assertEqual(self.stop_calls, ["a", "b"])

    def test_missing_server_manager_state_is_non_fatal(self) -> None:
        def boom():
            raise RuntimeError("state unreadable")

        server_manager.list_servers = boom
        # Must not raise — daemon teardown should never be blocked by this.
        self.assertEqual(self.launcher.stop_model_servers(), 0)


if __name__ == "__main__":
    unittest.main()
