from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skills_sdk.registry import SkillRegistry


class RegistrySmokeTests(unittest.TestCase):
    def test_echo_discovered(self) -> None:
        registry = SkillRegistry()
        registry.discover(ROOT / "skills")
        record = registry.get("echo.skill")
        self.assertIsNotNone(record)

    def test_fs_read_file_discovered(self) -> None:
        registry = SkillRegistry()
        registry.discover(ROOT / "skills")
        record = registry.get("fs.read_file")
        self.assertIsNotNone(record)


if __name__ == "__main__":
    unittest.main()
