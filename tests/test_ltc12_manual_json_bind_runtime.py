from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.modules.setdefault("httpx", SimpleNamespace(HTTPStatusError=Exception))

from app.role_catalog import RoleCatalog
from app.role_catalog_service import ensure_role_identity_by_name
from app.session_resolver import SessionResolver
from app.storage import Storage


class _LocalOnlyRouter:
    def supports(self, _model_override: str | None, _capability: str) -> bool:
        return False


class LTC12ManualJsonBindRuntimeTests(unittest.TestCase):
    def test_manual_json_bind_uses_prompt_and_instruction_in_session_warmup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            group = storage.upsert_group(-100333, "team")
            team_id = group.team_id or 0

            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            (root / "manual_role.json").write_text(
                json.dumps(
                    {
                        "role_name": "manual_role",
                        "system_prompt": "json prompt",
                        "instruction": "json instruction",
                        "is_active": True,
                    }
                ),
                encoding="utf-8",
            )
            catalog = RoleCatalog.load(root)
            storage.attach_role_catalog(catalog)
            runtime = SimpleNamespace(role_catalog=catalog)

            role = ensure_role_identity_by_name(
                runtime=runtime,  # type: ignore[arg-type]
                storage=storage,
                role_name="manual_role",
            )
            storage.bind_master_role_to_team(team_id, role.role_id)

            role_for_team = storage.get_role_for_team_by_name(team_id, "manual_role")
            self.assertEqual(role_for_team.base_system_prompt, "json prompt")
            self.assertEqual(role_for_team.extra_instruction, "json instruction")

            resolver = SessionResolver(storage, _LocalOnlyRouter())  # type: ignore[arg-type]
            session_id = self._run(
                resolver.ensure_session(
                    telegram_user_id=77,
                    team_id=team_id,
                    role=role_for_team,
                    session_token="unused",
                    model_override=None,
                )
            )
            messages = storage.list_conversation_messages(session_id)
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0][0], "system")
            self.assertIn("json prompt", messages[0][1])
            self.assertIn("json instruction", messages[0][1])

    def test_team_override_has_priority_over_json_master_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            group = storage.upsert_group(-100334, "team")
            team_id = group.team_id or 0
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            (root / "manual_role.json").write_text(
                json.dumps(
                    {
                        "role_name": "manual_role",
                        "base_system_prompt": "json prompt",
                        "extra_instruction": "json instruction",
                        "is_active": True,
                    }
                ),
                encoding="utf-8",
            )
            catalog = RoleCatalog.load(root)
            storage.attach_role_catalog(catalog)
            runtime = SimpleNamespace(role_catalog=catalog)
            role = ensure_role_identity_by_name(
                runtime=runtime,  # type: ignore[arg-type]
                storage=storage,
                role_name="manual_role",
            )
            storage.bind_master_role_to_team(team_id, role.role_id)
            storage.set_team_role_prompt(team_id, role.role_id, "team prompt")
            storage.set_team_role_extra_instruction(team_id, role.role_id, "team instruction")
            role_for_team = storage.get_role_for_team_by_name(team_id, "manual_role")
            resolver = SessionResolver(storage, _LocalOnlyRouter())  # type: ignore[arg-type]
            session_id = self._run(
                resolver.ensure_session(
                    telegram_user_id=78,
                    team_id=team_id,
                    role=role_for_team,
                    session_token="unused",
                    model_override=None,
                )
            )
            messages = storage.list_conversation_messages(session_id)
            self.assertIn("team prompt", messages[0][1])
            self.assertIn("team instruction", messages[0][1])

    def test_runtime_resolves_identity_from_file_name_when_json_role_name_differs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite3"
            storage = Storage(db_path)
            group = storage.upsert_group(-100335, "team")
            team_id = group.team_id or 0
            root = Path(td) / "roles_catalog"
            root.mkdir(parents=True, exist_ok=True)
            (root / "file_identity.json").write_text(
                json.dumps(
                    {
                        "role_name": "payload_name",
                        "base_system_prompt": "prompt by file identity",
                        "extra_instruction": "instruction by file identity",
                        "is_active": True,
                    }
                ),
                encoding="utf-8",
            )
            catalog = RoleCatalog.load(root)
            storage.attach_role_catalog(catalog)
            runtime = SimpleNamespace(role_catalog=catalog)
            role = ensure_role_identity_by_name(
                runtime=runtime,  # type: ignore[arg-type]
                storage=storage,
                role_name="file_identity",
            )
            storage.bind_master_role_to_team(team_id, role.role_id)
            role_for_team = storage.get_role_for_team_by_name(team_id, "file_identity")
            self.assertEqual(role_for_team.base_system_prompt, "prompt by file identity")
            self.assertEqual(role_for_team.extra_instruction, "instruction by file identity")

    @staticmethod
    def _run(coro):
        import asyncio

        return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
