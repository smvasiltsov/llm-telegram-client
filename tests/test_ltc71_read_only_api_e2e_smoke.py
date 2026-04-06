from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_IMPORT_ERROR: Exception | None = None
try:
    import pydantic  # noqa: F401
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover - dependency gap in environment
    _IMPORT_ERROR = exc

from app.application.authz import OwnerOnlyAuthzService
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.storage import Storage


class LTC71ReadOnlyApiE2ESmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        if _IMPORT_ERROR is not None:
            self.skipTest(f"fastapi/pydantic deps are unavailable: {_IMPORT_ERROR}")
        try:
            from app.interfaces.api.read_only_app import build_read_only_fastapi_app as builder
        except Exception as exc:
            self.skipTest(f"api transport dependencies are unavailable: {exc}")
        self._builder = builder

    def test_build_app_runtime_and_serve_read_request(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "ltc71.sqlite3"
            storage = Storage(db_path)
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9711, "e2e")
                role = storage.upsert_role(
                    role_name="dev",
                    description="e2e",
                    base_system_prompt="sp",
                    extra_instruction="ei",
                    llm_model=None,
                    is_active=True,
                )
                storage.ensure_group_role(group.group_id, role.role_id)
                team_role_id = storage.resolve_team_role_id(int(group.team_id or 0), role.role_id, ensure_exists=True)
                if team_role_id is None:
                    raise AssertionError("team_role_id missing")
                storage.ensure_team_role_runtime_status(int(team_role_id))

            runtime = SimpleNamespace(
                storage=storage,
                role_runtime_status_service=RoleRuntimeStatusService(storage, free_transition_delay_sec=0),
                role_dispatch_queue_service=SimpleNamespace(),
                free_transition_delay_sec=0,
                authz_service=OwnerOnlyAuthzService(owner_user_id=700),
            )
            app = self._builder(runtime)
            client = TestClient(app)

            response = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "700", "X-Correlation-Id": "e2e-corr"})
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn("items", payload)
            self.assertIn("meta", payload)
            self.assertEqual(response.headers.get("X-Correlation-Id"), "e2e-corr")


if __name__ == "__main__":
    unittest.main()
