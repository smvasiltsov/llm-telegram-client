from __future__ import annotations

import importlib
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from app.prepost_processing.registry import PrePostProcessingRegistry


class PrePostProcessingRegistryTests(unittest.TestCase):
    def test_discover_loads_valid_prepost_processing(self) -> None:
        registry = PrePostProcessingRegistry()
        registry.discover("prepost_processing")

        record = registry.get("echo")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.spec.prepost_processing_id, "echo")
        self.assertEqual(record.spec.version, "0.1.0")

    def test_discover_skips_invalid_prepost_processing_and_loads_valid_one(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            processors_pkg = base / "prepost_processing"
            processors_pkg.mkdir(parents=True)
            (processors_pkg / "__init__.py").write_text("", encoding="utf-8")

            self._write_good_processor(processors_pkg)
            self._write_bad_processor(processors_pkg)

            pre_modules = [name for name in sys.modules if name == "prepost_processing" or name.startswith("prepost_processing.")]
            for name in pre_modules:
                sys.modules.pop(name, None)

            sys.path.insert(0, str(base))
            try:
                importlib.invalidate_caches()
                registry = PrePostProcessingRegistry()
                registry.discover(processors_pkg)
            finally:
                sys.path.remove(str(base))
                for name in [n for n in sys.modules if n == "prepost_processing" or n.startswith("prepost_processing.")]:
                    sys.modules.pop(name, None)

            self.assertIsNotNone(registry.get("good"))
            self.assertIsNone(registry.get("bad"))

    @staticmethod
    def _write_good_processor(processors_pkg: Path) -> None:
        good_dir = processors_pkg / "good"
        good_dir.mkdir()
        (good_dir / "__init__.py").write_text("", encoding="utf-8")
        (good_dir / "processor.yaml").write_text(
            "\n".join(
                [
                    "id: good",
                    "version: 0.0.1",
                    "entrypoint: processor:create_processor",
                ]
            ),
            encoding="utf-8",
        )
        (good_dir / "processor.py").write_text(
            textwrap.dedent(
                """
                from app.prepost_processing.contract import PrePostProcessingSpec, PrePostProcessingResult

                class GoodProcessor:
                    def describe(self):
                        return PrePostProcessingSpec(prepost_processing_id=\"good\", name=\"Good\", version=\"0.0.1\")

                    def validate_config(self, config):
                        return []

                    def run(self, ctx, payload):
                        return PrePostProcessingResult(status=\"ok\", output={\"ok\": True})

                def create_processor():
                    return GoodProcessor()
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _write_bad_processor(processors_pkg: Path) -> None:
        bad_dir = processors_pkg / "bad"
        bad_dir.mkdir()
        (bad_dir / "__init__.py").write_text("", encoding="utf-8")
        (bad_dir / "processor.yaml").write_text(
            "\n".join(
                [
                    "id: bad",
                    "version: 0.0.1",
                    "entrypoint: processor:create_processor",
                ]
            ),
            encoding="utf-8",
        )
        (bad_dir / "processor.py").write_text(
            textwrap.dedent(
                """
                class BadProcessor:
                    def describe(self):
                        return object()

                def create_processor():
                    return BadProcessor()
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
