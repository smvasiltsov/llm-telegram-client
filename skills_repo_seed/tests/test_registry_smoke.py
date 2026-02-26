from __future__ import annotations

import unittest

from mcp_skill_sdk.registry import SkillRegistry


class RegistrySmokeTests(unittest.TestCase):
    def test_echo_discovered(self) -> None:
        registry = SkillRegistry()
        registry.discover("skills")
        record = registry.get("echo")
        self.assertIsNotNone(record)


if __name__ == "__main__":
    unittest.main()
