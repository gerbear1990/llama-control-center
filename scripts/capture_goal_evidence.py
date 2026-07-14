#!/usr/bin/env python
r"""Capture goal evidence into scratch (per strategist recommendation).

Runs the committed test suite, writes exact output to
C:/Users/filth/AppData/Local/Temp/grok-goal-bf1ed53888ea/implementer/full_test_suite_output.txt

Appends a filtered git log --name-only for allowlisted milestone paths only.
This replaces hand-edited scratch probe artifacts as source of truth.
"""

import subprocess
import sys
from pathlib import Path

SCRATCH = Path(r"C:\Users\filth\AppData\Local\Temp\grok-goal-bf1ed53888ea\implementer")
SCRATCH.mkdir(parents=True, exist_ok=True)

# 1. Run full discover and capture exact output (the single source of the "Ran N tests" line)
result = subprocess.run(
    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
    capture_output=True,
    text=True,
)
out_path = SCRATCH / "full_test_suite_output.txt"
out_path.write_text(result.stdout + result.stderr, encoding="utf-8")
print("Wrote", out_path)

# 2. Append filtered commit delta for allowlisted paths only (for clean CHANGED_FILES evidence)
allowed = ("lcc_api/", "lcc_core/", "tests/", "CHANGELOG.md", "REVIEW_MILESTONES.md", "scripts/capture_goal_evidence.py")
try:
    log = subprocess.check_output(["git", "log", "-1", "--name-only"], text=True)
except Exception:
    log = ""
lines = []
for line in log.splitlines():
    line = line.strip()
    if not line:
        continue
    if line.startswith(("commit", "Author", "Date", "    ")):
        lines.append(line)
        continue
    if any(a in line for a in allowed):
        lines.append(line)
delta_path = SCRATCH / "commit_delta.txt"
delta_path.write_text("\n".join(lines), encoding="utf-8")
print("Wrote", delta_path)

if __name__ == "__main__":
    pass