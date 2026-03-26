from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.errors.interface import InterfaceConfigError
from app.interfaces.runtime.config import InterfaceRuntimeConfig
from app.interfaces.runtime.runner import InterfaceRuntimeRunner


class _CorePort:
    async def handle_event(self, event: object):
        return []


class InterfaceRuntimeRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_start_stop_invokes_adapter_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pkg = Path(td) / "tmp_rt"
            (pkg / "demo").mkdir(parents=True, exist_ok=True)
            (pkg / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "demo" / "__init__.py").write_text("", encoding="utf-8")
            (pkg / "demo" / "adapter.py").write_text(
                "class Adapter:\n"
                "  interface_id='demo'\n"
                "  started=False\n"
                "  stopped=False\n"
                "  async def start(self):\n"
                "    self.started=True\n"
                "  async def stop(self):\n"
                "    self.stopped=True\n"
                "def create_adapter(core_port, runtime, config):\n"
                "  return Adapter()\n",
                encoding="utf-8",
            )

            runner = InterfaceRuntimeRunner(
                config=InterfaceRuntimeConfig(active_interface="demo", modules_dir="tmp_rt", runtime_mode="single"),
                runtime=SimpleNamespace(),
                core_port=_CorePort(),
                adapter_config={},
            )
            await self._with_path(Path(td), runner.start)
            assert runner.adapter is not None
            self.assertTrue(runner.adapter.started)
            await self._with_path(Path(td), runner.stop)
            self.assertTrue(runner.adapter.stopped)

    async def test_runner_rejects_unsupported_mode(self) -> None:
        runner = InterfaceRuntimeRunner(
            config=InterfaceRuntimeConfig(active_interface="demo", modules_dir="tmp_rt", runtime_mode="multi"),
            runtime=SimpleNamespace(),
            core_port=_CorePort(),
        )
        with self.assertRaises(InterfaceConfigError):
            runner.build()

    @staticmethod
    async def _with_path(base: Path, callback):
        import sys

        marker = str(base)
        sys.path.insert(0, marker)
        try:
            return await callback()
        finally:
            sys.path = [item for item in sys.path if item != marker]
            for key in list(sys.modules.keys()):
                if key == "tmp_rt" or key.startswith("tmp_rt."):
                    sys.modules.pop(key, None)


if __name__ == "__main__":
    unittest.main()
