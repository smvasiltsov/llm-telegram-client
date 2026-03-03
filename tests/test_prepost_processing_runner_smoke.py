from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class PrePostProcessingRunnerSmokeTests(unittest.TestCase):
    def test_echo_prepost_processing_runner(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            sys.executable,
            str(root / "scripts" / "prepost_processing_runner.py"),
            "--prepost-processing-dir",
            str(root / "prepost_processing"),
            "--prepost-processing-id",
            "echo",
            "--phase",
            "pre",
            "--payload-json",
            '{"user_text":"hello"}',
            "--config-json",
            "{}",
            "--role-name",
            "dev",
        ]
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        data = json.loads(proc.stdout)
        self.assertEqual(data["prepost_processing_id"], "echo")
        self.assertEqual(data["result"]["status"], "ok")
        self.assertIn("output", data["result"])


if __name__ == "__main__":
    unittest.main()
