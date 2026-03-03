from __future__ import annotations

import unittest

from skills_sdk.registry import SkillRegistry


class RegistrySmokeTests(unittest.TestCase):
    def test_echo_discovered(self) -> None:
        registry = SkillRegistry()
        registry.discover("skills")
        record = registry.get("echo.skill")
        self.assertIsNotNone(record)

    def test_fs_read_file_discovered(self) -> None:
        registry = SkillRegistry()
        registry.discover("skills")
        record = registry.get("fs.read_file")
        self.assertIsNotNone(record)


if __name__ == "__main__":
    unittest.main()
