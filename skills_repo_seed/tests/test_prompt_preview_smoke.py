from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class PromptPreviewSmokeTests(unittest.TestCase):
    def test_preview_compact_contains_fs_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        cmd = [
            sys.executable,
            str(root / "scripts" / "skills_prompt_preview.py"),
            "--skills-dir",
            str(root / "skills"),
            "--enabled-skill-id",
            "fs.read_file",
            "--output",
            "input_json_compact",
        ]
        proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 2)
        self.assertEqual(lines[0], "INPUT_JSON:")
        payload = json.loads(lines[1])
        self.assertIn("skills", payload)
        available = payload["skills"]["available"]
        self.assertEqual(len(available), 1)
        self.assertEqual(available[0]["skill_id"], "fs.read_file")
        self.assertIn("input_schema", available[0])
        self.assertIn("debug", available[0])
        self.assertIn("config_contract_hints", available[0]["debug"])


if __name__ == "__main__":
    unittest.main()
