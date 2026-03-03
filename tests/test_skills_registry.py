from __future__ import annotations

import importlib
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from app.skills.registry import SkillRegistry


class SkillRegistryTests(unittest.TestCase):
    def test_discover_skips_invalid_skill_and_loads_valid_one(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            skills_pkg = base / "skills"
            skills_pkg.mkdir(parents=True)
            (skills_pkg / "__init__.py").write_text("", encoding="utf-8")

            self._write_good_skill(skills_pkg)
            self._write_bad_skill(skills_pkg)

            pre_modules = [name for name in sys.modules if name == "skills" or name.startswith("skills.")]
            for name in pre_modules:
                sys.modules.pop(name, None)

            sys.path.insert(0, str(base))
            try:
                importlib.invalidate_caches()
                registry = SkillRegistry()
                registry.discover(skills_pkg)
            finally:
                sys.path.remove(str(base))
                for name in [item for item in sys.modules if item == "skills" or item.startswith("skills.")]:
                    sys.modules.pop(name, None)

            self.assertIsNotNone(registry.get("good"))
            self.assertIsNone(registry.get("bad"))

    @staticmethod
    def _write_good_skill(skills_pkg: Path) -> None:
        good_dir = skills_pkg / "good"
        good_dir.mkdir()
        (good_dir / "__init__.py").write_text("", encoding="utf-8")
        (good_dir / "skill.yaml").write_text(
            "\n".join(
                [
                    "id: good",
                    "version: 0.0.1",
                    "entrypoint: skill:create_skill",
                ]
            ),
            encoding="utf-8",
        )
        (good_dir / "skill.py").write_text(
            textwrap.dedent(
                """
                from app.skills.contract import SkillResult, SkillSpec

                class GoodSkill:
                    def describe(self):
                        return SkillSpec(
                            skill_id="good",
                            name="Good",
                            version="0.0.1",
                            input_schema={"type": "object"},
                        )

                    def validate_config(self, config):
                        return []

                    def run(self, ctx, arguments, config):
                        return SkillResult(ok=True, output={"ok": True})

                def create_skill():
                    return GoodSkill()
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write_bad_skill(skills_pkg: Path) -> None:
        bad_dir = skills_pkg / "bad"
        bad_dir.mkdir()
        (bad_dir / "__init__.py").write_text("", encoding="utf-8")
        (bad_dir / "skill.yaml").write_text(
            "\n".join(
                [
                    "id: bad",
                    "version: 0.0.1",
                    "entrypoint: skill:create_skill",
                ]
            ),
            encoding="utf-8",
        )
        (bad_dir / "skill.py").write_text(
            textwrap.dedent(
                """
                class BadSkill:
                    def describe(self):
                        return object()

                def create_skill():
                    return BadSkill()
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
