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


class LTC79Stage5ApiE2ESmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        if _IMPORT_ERROR is not None:
            self.skipTest(f"fastapi/pydantic deps are unavailable: {_IMPORT_ERROR}")
        try:
            from app.interfaces.api.read_only_app import build_read_only_fastapi_app as builder
        except Exception as exc:
            self.skipTest(f"api transport dependencies are unavailable: {exc}")
        self._builder = builder

    def test_stage5_startup_and_qa_roundtrip_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "ltc79.sqlite3"
            storage = Storage(db_path)
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9791, "e2e-stage5")
                role = storage.upsert_role(
                    role_name="dev",
                    description="e2e",
                    base_system_prompt="sp",
                    extra_instruction="ei",
                    llm_model=None,
                    is_active=True,
                )
                storage.ensure_group_role(group.group_id, role.role_id)

            runtime = SimpleNamespace(
                storage=storage,
                role_runtime_status_service=RoleRuntimeStatusService(storage, free_transition_delay_sec=0),
                role_dispatch_queue_service=SimpleNamespace(),
                free_transition_delay_sec=0,
                authz_service=OwnerOnlyAuthzService(owner_user_id=700),
            )
            app = self._builder(runtime)
            client = TestClient(app)

            teams = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "700", "X-Correlation-Id": "stage5-e2e"})
            self.assertEqual(teams.status_code, 200)
            team_id = int(teams.json()["items"][0]["team_id"])

            roles = client.get(f"/api/v1/teams/{team_id}/roles", headers={"X-Owner-User-Id": "700"})
            self.assertEqual(roles.status_code, 200)
            role_id = int(roles.json()[0]["role_id"])
            team_role_id = int(storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)
            self.assertGreater(team_role_id, 0)

            create = client.post(
                "/api/v1/questions",
                headers={"X-Owner-User-Id": "700", "Idempotency-Key": "stage5-e2e-k1"},
                json={
                    "team_id": team_id,
                    "created_by_user_id": 700,
                    "text": "smoke question",
                    "team_role_id": team_role_id,
                    "question_id": "q-smoke",
                    "thread_id": "t-smoke",
                },
            )
            self.assertEqual(create.status_code, 202)
            self.assertEqual(create.headers.get("X-Correlation-Id"), "stage5-e2e")

            status = client.get("/api/v1/questions/q-smoke/status", headers={"X-Owner-User-Id": "700"})
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["status"], "accepted")

            journal = client.get(f"/api/v1/qa-journal?team_id={team_id}", headers={"X-Owner-User-Id": "700"})
            self.assertEqual(journal.status_code, 200)
            self.assertTrue(any(item["question_id"] == "q-smoke" for item in journal.json()["items"]))

    def test_stage5_orchestrator_fallback_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "ltc79_fallback.sqlite3"
            storage = Storage(db_path)
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9792, "e2e-stage5-fallback")
                role = storage.upsert_role(
                    role_name="dev",
                    description="e2e",
                    base_system_prompt="sp",
                    extra_instruction="ei",
                    llm_model=None,
                    is_active=True,
                )
                storage.ensure_group_role(group.group_id, role.role_id)
                team_id = int(group.team_id or 0)
                storage.set_team_role_mode(team_id, role.role_id, "orchestrator")

            runtime = SimpleNamespace(
                storage=storage,
                role_runtime_status_service=RoleRuntimeStatusService(storage, free_transition_delay_sec=0),
                role_dispatch_queue_service=SimpleNamespace(),
                free_transition_delay_sec=0,
                authz_service=OwnerOnlyAuthzService(owner_user_id=700),
            )
            app = self._builder(runtime)
            client = TestClient(app)

            teams = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "700"})
            self.assertEqual(teams.status_code, 200)
            team_id = int(teams.json()["items"][0]["team_id"])
            roles = client.get(f"/api/v1/teams/{team_id}/roles", headers={"X-Owner-User-Id": "700"})
            role_id = int(roles.json()[0]["role_id"])
            expected_team_role_id = int(storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)
            self.assertGreater(expected_team_role_id, 0)

            create = client.post(
                "/api/v1/questions",
                headers={"X-Owner-User-Id": "700", "Idempotency-Key": "stage5-e2e-fallback-k1"},
                json={
                    "team_id": team_id,
                    "created_by_user_id": 700,
                    "text": "fallback route without tag and team_role_id",
                    "question_id": "q-smoke-fallback",
                    "thread_id": "t-smoke-fallback",
                },
            )
            self.assertEqual(create.status_code, 202)
            self.assertEqual(create.json()["question"]["team_role_id"], expected_team_role_id)


if __name__ == "__main__":
    unittest.main()
