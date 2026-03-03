from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.skills.registry import SkillRegistry
from skills_sdk.contract import SkillContext


class BuiltinFSSkillsTests(unittest.TestCase):
    def test_registry_discovers_builtin_fs_skills(self) -> None:
        registry = SkillRegistry()
        registry.discover("skills")

        self.assertIsNotNone(registry.get("fs.read_file"))
        self.assertIsNotNone(registry.get("fs.list_dir"))
        self.assertIsNotNone(registry.get("fs.write_file"))

    def test_fs_read_file_reads_requested_range(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sample = root / "sample.txt"
            sample.write_text("abcdefghij", encoding="utf-8")

            registry = SkillRegistry()
            registry.discover("skills")
            record = registry.get("fs.read_file")
            assert record is not None

            result = record.instance.run(
                SkillContext(chain_id="c1", chat_id=1, user_id=2, role_id=3, role_name="r"),
                {"path": "sample.txt", "start_char": 2, "end_char": 6},
                {"root_dir": str(root)},
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.output["content"], "cdef")
            self.assertEqual(result.output["start_char"], 2)
            self.assertEqual(result.output["end_char"], 6)

    def test_fs_list_dir_lists_entries(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "b.txt").write_text("b", encoding="utf-8")
            (root / "a_dir").mkdir()

            registry = SkillRegistry()
            registry.discover("skills")
            record = registry.get("fs.list_dir")
            assert record is not None

            result = record.instance.run(
                SkillContext(chain_id="c1", chat_id=1, user_id=2, role_id=3, role_name="r"),
                {"path": "."},
                {"root_dir": str(root)},
            )

            self.assertTrue(result.ok)
            self.assertEqual([item["name"] for item in result.output["entries"]], ["a_dir", "b.txt"])

    def test_fs_write_file_replaces_and_appends(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            registry = SkillRegistry()
            registry.discover("skills")
            write_record = registry.get("fs.write_file")
            read_record = registry.get("fs.read_file")
            assert write_record is not None
            assert read_record is not None

            ctx = SkillContext(chain_id="c1", chat_id=1, user_id=2, role_id=3, role_name="r")
            created = write_record.instance.run(
                ctx,
                {"path": "notes.txt", "content": "hello", "mode": "replace"},
                {"root_dir": str(root)},
            )
            appended = write_record.instance.run(
                ctx,
                {"path": "notes.txt", "content": " world", "mode": "append"},
                {"root_dir": str(root)},
            )
            read_back = read_record.instance.run(
                ctx,
                {"path": "notes.txt"},
                {"root_dir": str(root)},
            )

            self.assertTrue(created.ok)
            self.assertTrue(created.output["created"])
            self.assertTrue(appended.ok)
            self.assertFalse(appended.output["created"])
            self.assertTrue(read_back.ok)
            self.assertEqual(read_back.output["content"], "hello world")


if __name__ == "__main__":
    unittest.main()
