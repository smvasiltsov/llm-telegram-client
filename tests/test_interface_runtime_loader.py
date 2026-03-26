from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.contracts.interface_io import OutboundAction
from app.core.errors.interface import InterfaceContractError, InterfaceLoadError
from app.interfaces.runtime.loader import load_interface_adapter
from app.interfaces.runtime.registry import InterfaceDescriptor


class _FakeCorePort:
    async def handle_event(self, event: object) -> list[OutboundAction]:
        return []


class InterfaceRuntimeLoaderTests(unittest.TestCase):
    def test_missing_module_raises_interface_load_error(self) -> None:
        descriptor = InterfaceDescriptor(interface_id="missing", module_path="tmp_pkg_for_loader.missing.adapter")
        with self.assertRaises(InterfaceLoadError):
            load_interface_adapter(
                descriptor=descriptor,
                core_port=_FakeCorePort(),
                runtime=SimpleNamespace(),
            )

    def test_missing_create_adapter_raises_contract_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "tmp_pkg_for_loader"
            self._write_package(root)
            (root / "telegram").mkdir(parents=True, exist_ok=True)
            (root / "telegram" / "__init__.py").write_text("", encoding="utf-8")
            (root / "telegram" / "adapter.py").write_text("VALUE = 1\n", encoding="utf-8")
            self._with_path(
                Path(td),
                lambda: self.assertRaises(
                    InterfaceContractError,
                    load_interface_adapter,
                    descriptor=InterfaceDescriptor("telegram", "tmp_pkg_for_loader.telegram.adapter"),
                    core_port=_FakeCorePort(),
                    runtime=SimpleNamespace(),
                ),
            )

    def test_adapter_id_mismatch_raises_contract_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "tmp_pkg_for_loader"
            self._write_package(root)
            (root / "telegram").mkdir(parents=True, exist_ok=True)
            (root / "telegram" / "__init__.py").write_text("", encoding="utf-8")
            (root / "telegram" / "adapter.py").write_text(
                "class Adapter:\n"
                "    interface_id = 'discord'\n"
                "    async def start(self):\n"
                "        return None\n"
                "    async def stop(self):\n"
                "        return None\n"
                "\n"
                "def create_adapter(core_port, runtime, config):\n"
                "    return Adapter()\n",
                encoding="utf-8",
            )
            self._with_path(
                Path(td),
                lambda: self.assertRaises(
                    InterfaceContractError,
                    load_interface_adapter,
                    descriptor=InterfaceDescriptor("telegram", "tmp_pkg_for_loader.telegram.adapter"),
                    core_port=_FakeCorePort(),
                    runtime=SimpleNamespace(),
                ),
            )

    def test_valid_adapter_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "tmp_pkg_for_loader"
            self._write_package(root)
            (root / "telegram").mkdir(parents=True, exist_ok=True)
            (root / "telegram" / "__init__.py").write_text("", encoding="utf-8")
            (root / "telegram" / "adapter.py").write_text(
                "class Adapter:\n"
                "    interface_id = 'telegram'\n"
                "    async def start(self):\n"
                "        return None\n"
                "    async def stop(self):\n"
                "        return None\n"
                "\n"
                "def create_adapter(core_port, runtime, config):\n"
                "    return Adapter()\n",
                encoding="utf-8",
            )
            result = self._with_path(
                Path(td),
                lambda: load_interface_adapter(
                    descriptor=InterfaceDescriptor("telegram", "tmp_pkg_for_loader.telegram.adapter"),
                    core_port=_FakeCorePort(),
                    runtime=SimpleNamespace(),
                ),
            )
            self.assertEqual(result.interface_id, "telegram")

    @staticmethod
    def _write_package(root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "__init__.py").write_text("", encoding="utf-8")

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
                if key == "tmp_pkg_for_loader" or key.startswith("tmp_pkg_for_loader."):
                    sys.modules.pop(key, None)


if __name__ == "__main__":
    unittest.main()
