"""Launch smoke tests (committed, no injection/dummy) for AC4 / verif step 2.

Starts lcc_api on fixed ports, waits for Uvicorn strings in log,
polls /health, asserts /api/servers 200 + 'servers' key.
Runs on two ports to cover "twice".
"""

import unittest
import subprocess
import time
import urllib.request
import json
import re
import sys
from pathlib import Path


class LaunchSmokeTests(unittest.TestCase):
    def _smoke(self, port: int):
        log_file = Path(f"lcc_smoke_{port}.log")
        proc = None
        try:
            cmd = [sys.executable, "-m", "lcc_api", "--host", "127.0.0.1", "--port", str(port)]
            with open(log_file, "w", encoding="utf-8") as lf:
                proc = subprocess.Popen(cmd, stdout=lf, stderr=lf)
            # Wait for the "Uvicorn running" line and extract actual bound port
            bound_port = None
            for _ in range(60):
                time.sleep(0.5)
                try:
                    content = log_file.read_text(encoding="utf-8", errors="replace")
                    m = re.search(r"Uvicorn running on http://127.0.0.1:(\d+)", content)
                    if m:
                        bound_port = int(m.group(1))
                        break
                except Exception:
                    pass
            self.assertIsNotNone(bound_port, "Uvicorn running line with port not found in log")
            content = log_file.read_text(encoding="utf-8", errors="replace")
            self.assertIn("Uvicorn running", content)
            self.assertIn("Application startup complete", content)
            # Poll /health until 200
            base = f"http://127.0.0.1:{bound_port}"
            healthy = False
            for _ in range(30):
                try:
                    with urllib.request.urlopen(base + "/health", timeout=1) as resp:
                        if getattr(resp, "status", 200) == 200:
                            healthy = True
                            break
                except Exception:
                    pass
                time.sleep(0.5)
            self.assertTrue(healthy, "/health did not return 200 in time")
            # Hit /api/servers
            with urllib.request.urlopen(base + "/api/servers", timeout=2) as resp:
                self.assertEqual(getattr(resp, "status", 200), 200)
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
                self.assertIn("servers", data)
        finally:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            try:
                log_file.unlink()
            except Exception:
                pass

    def test_launch_smoke_18717(self):
        self._smoke(18717)

    def test_launch_smoke_18718(self):
        self._smoke(18718)


if __name__ == "__main__":
    unittest.main()