from __future__ import annotations

import sys
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch


def _install_telegram_stubs_if_needed() -> None:
    if "httpx" not in sys.modules:
        httpx = types.ModuleType("httpx")
        httpx.AsyncClient = object
        sys.modules["httpx"] = httpx

    if "telegram" in sys.modules:
        return
    telegram = types.ModuleType("telegram")
    telegram.Update = object
    telegram.Bot = object
    sys.modules["telegram"] = telegram

    constants = types.ModuleType("telegram.constants")
    constants.ChatMemberStatus = SimpleNamespace(
        MEMBER="member",
        ADMINISTRATOR="administrator",
        OWNER="owner",
    )
    sys.modules["telegram.constants"] = constants

    errors = types.ModuleType("telegram.error")
    class _Err(Exception):
        pass
    errors.BadRequest = _Err
    errors.Forbidden = _Err
    errors.NetworkError = _Err
    errors.TimedOut = _Err
    sys.modules["telegram.error"] = errors

    ext = types.ModuleType("telegram.ext")
    ext.ContextTypes = SimpleNamespace(DEFAULT_TYPE=object)
    sys.modules["telegram.ext"] = ext


_install_telegram_stubs_if_needed()

from app.application.use_cases.group_runtime import prepare_group_buffer_plan
from app.handlers.membership import handle_group_seen
from app.services.group_reconcile import reconcile_active_groups
from app.storage import Storage


class _TxStorage:
    def __init__(self) -> None:
        self.in_tx = False
        self.tx_calls = 0
        self.upsert_calls = 0
        self.set_active_calls = 0

    @contextmanager
    def transaction(self, *, immediate: bool = False):
        self.tx_calls += 1
        self.in_tx = True
        try:
            yield self
        finally:
            self.in_tx = False

    def list_team_bindings(self, interface_type: str, active_only: bool):
        return [SimpleNamespace(external_id="10", external_title="g")]

    def upsert_telegram_team_binding(self, chat_id: int, title: str | None, *, is_active: bool = True) -> int:
        if not self.in_tx:
            raise AssertionError("upsert_telegram_team_binding outside tx")
        self.upsert_calls += 1
        return int(chat_id)

    def set_telegram_team_binding_active(self, chat_id: int, is_active: bool) -> None:
        if not self.in_tx:
            raise AssertionError("set_telegram_team_binding_active outside tx")
        self.set_active_calls += 1

    def list_roles_for_team(self, team_id: int):
        return []

    def get_enabled_orchestrator_for_team(self, team_id: int):
        return None


class _FakeBot:
    id = 1

    async def get_chat_member(self, chat_id: int, bot_id: int):
        return SimpleNamespace(status="member")

    async def get_chat(self, chat_id: int):
        return SimpleNamespace(id=chat_id, title=f"g-{chat_id}")


class LTC60StartupUowGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconcile_active_groups_uses_outer_transaction_for_writes(self) -> None:
        storage = _TxStorage()
        checked, deactivated = await reconcile_active_groups(_FakeBot(), storage)
        self.assertEqual(checked, 1)
        self.assertEqual(deactivated, 0)
        self.assertEqual(storage.tx_calls, 1)
        self.assertEqual(storage.upsert_calls, 1)

    async def test_membership_group_seen_writes_inside_transaction(self) -> None:
        storage = _TxStorage()
        runtime = SimpleNamespace(storage=storage)
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}))
        update = SimpleNamespace(effective_chat=SimpleNamespace(id=77, title="grp", type="group"))
        with patch("app.handlers.membership.seed_team_roles"):
            await handle_group_seen(update, context)
        self.assertEqual(storage.tx_calls, 1)
        self.assertEqual(storage.upsert_calls, 1)

    def test_prepare_group_buffer_plan_wraps_team_binding_write_with_transaction(self) -> None:
        storage = _TxStorage()
        runtime = SimpleNamespace(owner_user_id=7, bot_username="bot", require_bot_mention=False)
        with patch("app.application.use_cases.group_runtime.refresh_role_catalog"):
            with patch("app.application.use_cases.group_runtime.seed_team_roles"):
                result = prepare_group_buffer_plan(
                    storage=storage,
                    runtime=runtime,
                    chat_id=100,
                    chat_title="grp",
                    user_id=7,
                    text="hello",
                )
        self.assertTrue(result.is_ok)
        self.assertEqual(storage.tx_calls, 1)
        self.assertEqual(storage.upsert_calls, 1)

    async def test_reconcile_active_groups_rolls_back_on_apply_failure(self) -> None:
        with TemporaryDirectory() as td:
            db_path = Path(td) / "ltc60.sqlite3"
            storage = Storage(db_path)
            with storage.transaction(immediate=True):
                storage.upsert_telegram_team_binding(10, "grp", is_active=True)
            storage.enable_write_uow_guard()

            def _failing_apply(s: Storage, writes) -> None:
                # Simulate partial write attempt inside reconcile apply-phase.
                s.set_telegram_team_binding_active(10, False)
                raise RuntimeError("apply failed")

            with patch("app.services.group_reconcile.apply_reconcile_active_groups_writes", side_effect=_failing_apply):
                with self.assertRaises(RuntimeError):
                    await reconcile_active_groups(_FakeBot(), storage)

            binding = storage.get_team_binding(interface_type="telegram", external_id="10")
            self.assertTrue(binding.is_active)


if __name__ == "__main__":
    unittest.main()
