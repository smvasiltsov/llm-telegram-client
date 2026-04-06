from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.role_catalog import RoleCatalog
from app.role_catalog_service import create_master_role_json, update_master_role_json
from app.storage import Storage

try:
    from app.handlers.callbacks import _handle_set_model, _is_owner_callback
    from app.handlers.messages_private import _process_pending_private_text

    TELEGRAM_HANDLERS_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency in CI
    TELEGRAM_HANDLERS_AVAILABLE = False
    _handle_set_model = None
    _is_owner_callback = None
    _process_pending_private_text = None


class MasterDefaultsCatalogTests(unittest.TestCase):
    def test_update_master_role_json_updates_selected_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            storage = Storage(db_path)
            runtime = SimpleNamespace(role_catalog=RoleCatalog.load(root))

            role_id = create_master_role_json(
                runtime=runtime,  # type: ignore[arg-type]
                storage=storage,
                role_name="master_update_case",
                base_system_prompt="old prompt",
                extra_instruction="old instruction",
                llm_model=None,
            )
            self.assertGreater(role_id, 0)

            update_master_role_json(
                runtime=runtime,  # type: ignore[arg-type]
                storage=storage,
                role_name="master_update_case",
                base_system_prompt="new prompt",
            )
            role = storage.get_role_by_name("master_update_case")
            self.assertEqual(role.base_system_prompt, "new prompt")
            self.assertEqual(role.extra_instruction, "old instruction")
            self.assertIsNone(role.llm_model)

    def test_update_master_role_json_can_set_model_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            storage = Storage(db_path)
            runtime = SimpleNamespace(role_catalog=RoleCatalog.load(root))

            create_master_role_json(
                runtime=runtime,  # type: ignore[arg-type]
                storage=storage,
                role_name="master_model_case",
                base_system_prompt="p",
                extra_instruction="i",
                llm_model="provider:model",
            )
            update_master_role_json(
                runtime=runtime,  # type: ignore[arg-type]
                storage=storage,
                role_name="master_model_case",
                llm_model=None,
            )
            role = storage.get_role_by_name("master_model_case")
            self.assertIsNone(role.llm_model)


@unittest.skipUnless(TELEGRAM_HANDLERS_AVAILABLE, "telegram handlers unavailable in test env")
class MasterDefaultsTelegramFlowTests(unittest.IsolatedAsyncioTestCase):
    class _FakeQuery:
        def __init__(self, user_id: int) -> None:
            self.from_user = SimpleNamespace(id=user_id)
            self.answers: list[str | None] = []
            self.edits: list[str] = []

        async def answer(self, text: str | None = None) -> None:
            self.answers.append(text)

        async def edit_message_text(self, text: str, reply_markup=None) -> None:  # noqa: ANN001
            self.edits.append(text)

    class _FakeBot:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send_message(self, chat_id: int, text: str, reply_markup=None) -> None:  # noqa: ANN001
            self.sent.append(text)

    class _FakePendingStore:
        def peek(self, user_id: int):  # noqa: ANN001
            return None

    async def test_owner_callback_guard_blocks_non_owner(self) -> None:
        runtime = SimpleNamespace(owner_user_id=100)
        query = self._FakeQuery(user_id=200)
        ok = await _is_owner_callback(query, runtime)  # type: ignore[misc]
        self.assertFalse(ok)
        self.assertEqual(len(query.answers), 1)

    async def test_master_set_model_rejects_model_outside_registry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            role = storage.upsert_role(
                role_name="mrole_invalid_model",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            runtime = SimpleNamespace(
                provider_model_map={},
                provider_registry={},
                role_catalog=RoleCatalog.load(Path(td) / "roles_catalog"),
                storage=storage,
            )
            query = self._FakeQuery(user_id=1)
            handled = await _handle_set_model(  # type: ignore[misc]
                query,
                f"msetmodel:1:{role.role_id}:missing:model",
                storage,
                runtime,
                provider_model_map=runtime.provider_model_map,
                provider_registry=runtime.provider_registry,
            )
            self.assertTrue(handled)
            self.assertTrue(any("не найдена" in msg for msg in query.edits))

    async def test_master_prompt_limit_validation_in_private_pending_flow(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            role = storage.upsert_role(
                role_name="mrole_prompt_limit",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            runtime = SimpleNamespace(
                storage=storage,
                pending_prompts={},
                pending_role_ops={42: {"mode": "master_update", "step": "master_prompt", "role_id": role.role_id}},
                pending_store=self._FakePendingStore(),
                role_catalog=RoleCatalog.load(root),
            )
            bot = self._FakeBot()
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"runtime": runtime}), bot=bot)

            processed = await _process_pending_private_text(
                user_id=42,
                chat_id=42,
                text="x" * 16001,
                context=context,  # type: ignore[misc]
            )
            self.assertTrue(processed)
            self.assertTrue(any("16000" in msg for msg in bot.sent))
            self.assertIn(42, runtime.pending_role_ops)


if __name__ == "__main__":
    unittest.main()
