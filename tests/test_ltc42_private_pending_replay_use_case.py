from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.application.use_cases.private_pending_replay import build_pending_replay_dispatch_plan
from app.pending_store import PendingMessageRecord
from app.role_catalog import RoleCatalog
from app.storage import Storage


class _FakeCipher:
    def decrypt(self, value: str) -> str:
        return f"dec:{value}"


class LTC42PrivatePendingReplayUseCaseTests(unittest.TestCase):
    def _bootstrap(self) -> tuple[Storage, SimpleNamespace, int]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        storage = Storage(Path(td.name) / "test.sqlite3")
        catalog_dir = Path(td.name) / "roles_catalog"
        catalog_dir.mkdir(parents=True, exist_ok=True)
        (catalog_dir / "dev.json").write_text(
            (
                "{\n"
                '  "schema_version": 1,\n'
                '  "role_name": "dev",\n'
                '  "description": "d",\n'
                '  "base_system_prompt": "sp",\n'
                '  "extra_instruction": "ei",\n'
                '  "llm_model": null,\n'
                '  "is_active": true\n'
                "}\n"
            ),
            encoding="utf-8",
        )
        runtime = SimpleNamespace(role_catalog=RoleCatalog.load(catalog_dir))
        group = storage.upsert_group(-4301, "g")
        role = storage.upsert_role(
            role_name="dev",
            description="d",
            base_system_prompt="sp",
            extra_instruction="ei",
            llm_model=None,
            is_active=True,
        )
        storage.ensure_group_role(group.group_id, role.role_id)
        return storage, runtime, int(group.team_id or 0)

    def test_plan_skip_when_pending_absent(self) -> None:
        storage, runtime, _ = self._bootstrap()
        result = build_pending_replay_dispatch_plan(
            storage=storage,
            runtime=runtime,
            user_id=1,
            pending_msg=None,
            roles_require_auth_fn=lambda **_: False,
            cipher=_FakeCipher(),
        )
        self.assertTrue(result.is_ok)
        assert result.value is not None
        self.assertEqual(result.value.action, "skip")
        self.assertTrue(result.value.should_clear_counters)

    def test_plan_request_token_when_auth_required(self) -> None:
        storage, runtime, team_id = self._bootstrap()
        pending_msg: PendingMessageRecord = {
            "chat_id": -4301,
            "team_id": team_id,
            "message_id": 10,
            "role_name": "dev",
            "content": "hello",
            "reply_text": None,
        }
        result = build_pending_replay_dispatch_plan(
            storage=storage,
            runtime=runtime,
            user_id=1,
            pending_msg=pending_msg,
            roles_require_auth_fn=lambda **_: True,
            cipher=_FakeCipher(),
        )
        self.assertTrue(result.is_ok)
        assert result.value is not None
        self.assertEqual(result.value.action, "request_token")
        self.assertEqual(result.value.chat_id, -4301)

    def test_plan_dispatch_with_decrypted_token(self) -> None:
        storage, runtime, team_id = self._bootstrap()
        storage.upsert_user(1, "u")
        storage.upsert_auth_token(1, "enc")
        with storage.transaction(immediate=True):
            storage.set_user_authorized(telegram_user_id=1, is_authorized=True)
        pending_msg: PendingMessageRecord = {
            "chat_id": -4301,
            "team_id": team_id,
            "message_id": 11,
            "role_name": "dev",
            "content": "hello",
            "reply_text": "rt",
        }
        result = build_pending_replay_dispatch_plan(
            storage=storage,
            runtime=runtime,
            user_id=1,
            pending_msg=pending_msg,
            roles_require_auth_fn=lambda **_: True,
            cipher=_FakeCipher(),
        )
        self.assertTrue(result.is_ok)
        assert result.value is not None
        self.assertEqual(result.value.action, "dispatch")
        self.assertEqual(result.value.session_token, "dec:enc")
        self.assertEqual(len(result.value.roles), 1)
