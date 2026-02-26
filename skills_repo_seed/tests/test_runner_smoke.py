from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class RunnerSmokeTests(unittest.TestCase):
    def test_echo_runner(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            sys.executable,
            str(root / "scripts" / "skill_runner.py"),
            "--skills-dir",
            str(root / "skills"),
            "--skill-id",
            "echo",
            "--phase",
            "pre",
            "--payload-json",
            '{"user_text":"hello"}',
        ]
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        data = json.loads(proc.stdout)
        self.assertEqual(data["skill_id"], "echo")
        self.assertEqual(data["result"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
