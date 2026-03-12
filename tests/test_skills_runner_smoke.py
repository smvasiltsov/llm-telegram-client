from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SkillsRunnerSmokeTests(unittest.TestCase):
    def test_list_includes_fs_read_file(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            sys.executable,
            str(root / "scripts" / "skills_runner.py"),
            "--skills-dir",
            str(root / "skills"),
            "list",
            "--skill-id",
            "fs.read_file",
        ]
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        data = json.loads(proc.stdout)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["skills"][0]["skill_id"], "fs.read_file")

    def test_exec_fs_read_file(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            sandbox = Path(td)
            (sandbox / "sample.txt").write_text("abcdefghij", encoding="utf-8")
            cmd = [
                sys.executable,
                str(root / "scripts" / "skills_runner.py"),
                "--skills-dir",
                str(root / "skills"),
                "exec",
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
            self.assertEqual(data["skill"]["skill_id"], "fs.read_file")
            self.assertEqual(data["result"]["ok"], True)
            self.assertEqual(data["result"]["output"]["content"], "cdef")


if __name__ == "__main__":
    unittest.main()
