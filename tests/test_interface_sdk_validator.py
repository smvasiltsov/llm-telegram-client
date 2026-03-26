from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from interfaces_sdk.validator import validate_adapter_contract


class InterfaceSdkValidatorTests(unittest.TestCase):
    def test_validator_passes_for_valid_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td) / "tmp_ifaces"
            (pkg / "demo").mkdir(parents=True, exist_ok=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "demo" / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "demo" / "adapter.py").write_text(
                "class Adapter:\n"
                "  interface_id='demo'\n"
                "  async def start(self):\n"
                "    return None\n"
                "  async def stop(self):\n"
                "    return None\n"
                "def create_adapter(core_port, runtime, config):\n"
                "  return Adapter()\n",
                encoding="utf-8",
            )
            errors = self._with_path(Path(td), lambda: validate_adapter_contract("tmp_ifaces.demo.adapter", "demo"))
            self.assertEqual(errors, [])

    def test_validator_reports_missing_factory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td) / "tmp_ifaces"
            (pkg / "demo").mkdir(parents=True, exist_ok=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "demo" / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "demo" / "adapter.py").write_text("x=1\n", encoding="utf-8")
            errors = self._with_path(Path(td), lambda: validate_adapter_contract("tmp_ifaces.demo.adapter", "demo"))
            self.assertTrue(any(item.startswith("missing_factory:") for item in errors))

    @staticmethod
    def _with_path(base: Path, callback):
        import sys

        marker = str(base)
        sys.path.insert(0, marker)
        try:
            return callback()
        finally:
            sys.path = [item for item in sys.path if item != marker]
            for key in list(sys.modules.keys()):
                if key == "tmp_ifaces" or key.startswith("tmp_ifaces."):
                    sys.modules.pop(key, None)


if __name__ == "__main__":
    unittest.main()
