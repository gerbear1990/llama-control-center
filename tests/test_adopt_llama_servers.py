from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lcc_core.schema import ModelProfile


class ParseLlamaServerArgvTests(unittest.TestCase):
    def test_extracts_model_host_port_from_windows_launch(self) -> None:
        from lcc_core.server_manager import parse_llama_server_argv

        parsed = parse_llama_server_argv([
            r"C:\Users\filth\llama.cpp-cuda\llama-server.exe",
            "-m", r"C:\Users\filth\models\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-Q5_K_XL.gguf",
            "-mm", r"C:\Users\filth\models\Qwen3.8-27B-GGUF\mmproj-F16.gguf",
            "-ngl", "99", "-c", "200000", "--host", "0.0.0.0", "--port", "8081",
        ])
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["model_path"],
            r"C:\Users\filth\models\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-Q5_K_XL.gguf",
        )
        self.assertEqual(parsed["host"], "0.0.0.0")
        self.assertEqual(parsed["port"], 8081)

    def test_accepts_long_option_equals_form(self) -> None:
        from lcc_core.server_manager import parse_llama_server_argv

        parsed = parse_llama_server_argv([
            "llama-server", "--model=/models/foo.gguf", "--host=127.0.0.1", "--port=18100",
            "--alias=foo-bar",
        ])
        self.assertEqual(parsed["model_path"], "/models/foo.gguf")
        self.assertEqual(parsed["host"], "127.0.0.1")
        self.assertEqual(parsed["port"], 18100)
        self.assertEqual(parsed["alias"], "foo-bar")

    def test_rejects_non_llama_binary(self) -> None:
        from lcc_core.server_manager import parse_llama_server_argv

        self.assertIsNone(parse_llama_server_argv(["vllm", "serve", "--port", "8000"]))
        self.assertIsNone(parse_llama_server_argv([]))
        self.assertIsNone(parse_llama_server_argv(None))

    def test_parses_quoted_windows_command_line(self) -> None:
        from lcc_core.server_manager import parse_llama_server_command_line

        parsed = parse_llama_server_command_line(
            r'"C:\Users\filth\llama.cpp-cuda\llama-server.exe" -m '
            r"C:\Users\filth\models\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-Q5_K_XL.gguf "
            r"-mm C:\Users\filth\models\Qwen3.8-27B-GGUF\mmproj-F16.gguf "
            r"--host 0.0.0.0 --port 8081 -t 8"
        )
        self.assertIsNotNone(parsed)
        self.assertTrue(parsed["model_path"].endswith("Qwen3.8-27B-UD-Q5_K_XL.gguf"))
        self.assertEqual(parsed["host"], "0.0.0.0")
        self.assertEqual(parsed["port"], 8081)


class AdoptRunningLlamaServerTests(unittest.TestCase):
    def setUp(self) -> None:
        import lcc_core.server_manager as sm
        self.sm = sm
        self._tmp = tempfile.mkdtemp()
        self._state_file = Path(self._tmp) / "servers.json"
        self._orig_state_path = sm.state_path
        sm.state_path = lambda: self._state_file
        self._state_file.write_text(json.dumps({"servers": []}), encoding="utf-8")

    def tearDown(self) -> None:
        self.sm.state_path = self._orig_state_path
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _profiles(self) -> list[ModelProfile]:
        return [
            ModelProfile(
                mode="qwen3.8-27b-gguf",
                name="Qwen3.8-27B-GGUF",
                description="",
                model_path=r"C:\Users\filth\models\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-Q5_K_XL.gguf",
            )
        ]

    def _qwen_process(self, pid: int = 44120) -> dict:
        return {
            "pid": pid,
            "model_path": r"C:\Users\filth\models\Qwen3.8-27B-GGUF\Qwen3.8-27B-UD-Q5_K_XL.gguf",
            "host": "0.0.0.0",
            "port": 8081,
            "alias": None,
            "command_line": "llama-server.exe -m Qwen3.8-27B-UD-Q5_K_XL.gguf --port 8081",
        }

    def test_adopts_untracked_process_and_pins_matching_profile(self) -> None:
        added = self.sm.adopt_running_llama_servers(
            processes=[self._qwen_process()],
            profiles=self._profiles(),
        )
        self.assertEqual(added, 1)
        servers = self.sm.read_state()["servers"]
        self.assertEqual(len(servers), 1)
        server = servers[0]
        self.assertEqual(server["pid"], 44120)
        self.assertEqual(server["mode"], "qwen3.8-27b-gguf")
        self.assertEqual(server["port"], 8081)
        self.assertEqual(server["host"], "0.0.0.0")
        self.assertEqual(server["status"], "running")
        self.assertTrue(server["running"])
        self.assertEqual(server["origin"], "adopted")
        self.assertEqual(server["runtime"], "llama.cpp")

    def test_does_not_duplicate_already_tracked_pid(self) -> None:
        self.sm.adopt_running_llama_servers(
            processes=[self._qwen_process()],
            profiles=self._profiles(),
        )
        added = self.sm.adopt_running_llama_servers(
            processes=[self._qwen_process()],
            profiles=self._profiles(),
        )
        self.assertEqual(added, 0)
        self.assertEqual(len(self.sm.read_state()["servers"]), 1)

    def test_unmatched_model_still_appears(self) -> None:
        process = self._qwen_process()
        process["model_path"] = r"C:\models\orphan.gguf"
        added = self.sm.adopt_running_llama_servers(
            processes=[process],
            profiles=self._profiles(),
        )
        self.assertEqual(added, 1)
        server = self.sm.read_state()["servers"][0]
        self.assertEqual(server["mode"], "orphan")
        self.assertEqual(server["origin"], "adopted")

    def test_list_servers_adopts_before_returning(self) -> None:
        orig = self.sm._live_llama_server_processes
        self.sm._live_llama_server_processes = lambda: [self._qwen_process()]
        orig_profiles = self.sm._adopt_profiles
        self.sm._adopt_profiles = lambda: self._profiles()
        try:
            listed = self.sm.list_servers()
        finally:
            self.sm._live_llama_server_processes = orig
            self.sm._adopt_profiles = orig_profiles
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["mode"], "qwen3.8-27b-gguf")
        self.assertEqual(listed[0]["pid"], 44120)

    def test_list_servers_can_skip_adopt(self) -> None:
        orig = self.sm._live_llama_server_processes
        self.sm._live_llama_server_processes = lambda: [self._qwen_process()]
        try:
            listed = self.sm.list_servers(adopt=False)
        finally:
            self.sm._live_llama_server_processes = orig
        self.assertEqual(listed, [])

    def test_find_server_does_not_adopt(self) -> None:
        self._state_file.write_text(json.dumps({"servers": [{
            "id": "demo-1", "mode": "demo", "pid": 1, "status": "stopped",
        }]}), encoding="utf-8")
        orig = self.sm._live_llama_server_processes
        self.sm._live_llama_server_processes = lambda: [self._qwen_process()]
        orig_profiles = self.sm._adopt_profiles
        self.sm._adopt_profiles = lambda: self._profiles()
        try:
            found = self.sm._find_server(mode="demo")
            listed = self.sm.read_state()["servers"]
        finally:
            self.sm._live_llama_server_processes = orig
            self.sm._adopt_profiles = orig_profiles
        self.assertEqual(found["id"], "demo-1")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["mode"], "demo")
