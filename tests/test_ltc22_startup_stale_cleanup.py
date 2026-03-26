from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

from app.config import load_config
from app.storage import Storage

if "httpx" not in sys.modules:
    httpx_module = types.ModuleType("httpx")

    class _AsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    httpx_module.AsyncClient = _AsyncClient
    sys.modules["httpx"] = httpx_module

if "app.interfaces.telegram.adapter" not in sys.modules:
    adapter_module = types.ModuleType("app.interfaces.telegram.adapter")

    def _build_telegram_application(*args, **kwargs):
        return object()

    adapter_module.build_telegram_application = _build_telegram_application
    sys.modules["app.interfaces.telegram.adapter"] = adapter_module

from app.app_factory import build_runtime


class LTC22StartupStaleCleanupTests(unittest.TestCase):
    def test_build_runtime_cleans_stale_busy_statuses_on_startup(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            db_path = tmp / "startup_cleanup.sqlite3"
            storage = Storage(db_path)
            group = storage.upsert_group(-91001, "startup-cleanup-group")
            role = storage.upsert_role(
                role_name="startup_cleanup_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_role_id = int(storage.resolve_team_role_id(group.team_id or 0, role.role_id, ensure_exists=True) or 0)
            storage.ensure_team_role_runtime_status(team_role_id)
            storage.mark_team_role_runtime_busy(
                team_role_id,
                busy_request_id="req-startup-stale",
                busy_owner_user_id=77,
                busy_origin="group",
                preview_text="stale",
                preview_source="user",
                busy_since="2000-01-01T00:00:00+00:00",
                lease_expires_at="2000-01-01T00:01:00+00:00",
                now="2000-01-01T00:00:00+00:00",
            )

            config_path = tmp / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "telegram_bot_token": "token",
                        "database_path": str(db_path),
                        "encryption_key": "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
                        "owner_user_id": 1,
                        "runtime_status": {"free_transition_delay_sec": 0},
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(config_path)
            runtime = build_runtime(
                config=config,
                bot_username="bot",
                tools_bash_password="",
                providers_dir=(Path.cwd() / "llm_providers").resolve(),
                plugins_dir=(Path.cwd() / "plugins").resolve(),
                prepost_processing_dir=(Path.cwd() / "prepost_processing").resolve(),
                skills_dir=(Path.cwd() / "skills").resolve(),
                base_cwd=tmp,
            )
            self.assertIsNotNone(runtime)

            check_storage = Storage(db_path)
            status = check_storage.get_team_role_runtime_status(team_role_id)
            self.assertIsNotNone(status)
            self.assertEqual(status.status if status else None, "free")
            self.assertEqual(status.last_release_reason if status else None, "lease_expired_cleanup")


if __name__ == "__main__":
    unittest.main()
