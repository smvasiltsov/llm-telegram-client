from __future__ import annotations

import unittest
from types import SimpleNamespace


class TelegramAdapterContractTests(unittest.TestCase):
    def test_create_adapter_contract(self) -> None:
        try:
            from app.interfaces.telegram.adapter import create_adapter
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"telegram adapter import unavailable: {exc}")
            return

        class _CorePort:
            async def handle_event(self, event: object):
                return []

        runtime = SimpleNamespace(owner_user_id=1)
        adapter = create_adapter(core_port=_CorePort(), runtime=runtime, config={"telegram_bot_token": "x"})
        self.assertEqual(adapter.interface_id, "telegram")
        self.assertTrue(callable(getattr(adapter, "start", None)))
        self.assertTrue(callable(getattr(adapter, "stop", None)))


if __name__ == "__main__":
    unittest.main()
