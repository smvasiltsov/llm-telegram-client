from __future__ import annotations

import json
import subprocess
import sys
import tempfile
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
            "echo.skill",
            "--arguments-json",
            '{"message":"hello"}',
        ]
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        data = json.loads(proc.stdout)
        self.assertEqual(data["skill_id"], "echo.skill")
        self.assertEqual(data["result"]["ok"], True)

    def test_fs_read_file_runner(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            sandbox = Path(td)
            (sandbox / "sample.txt").write_text("abcdefghij", encoding="utf-8")
            cmd = [
                sys.executable,
                str(root / "scripts" / "skill_runner.py"),
                "--skills-dir",
                str(root / "skills"),
                "--skill-id",
                "fs.read_file",
                "--arguments-json",
                '{"path":"sample.txt","start_char":2,"end_char":6}',
                "--config-json",
                json.dumps({"root_dir": str(sandbox)}),
            ]
            proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            data = json.loads(proc.stdout)
            self.assertEqual(data["skill_id"], "fs.read_file")
            self.assertEqual(data["result"]["output"]["content"], "cdef")


if __name__ == "__main__":
    unittest.main()
