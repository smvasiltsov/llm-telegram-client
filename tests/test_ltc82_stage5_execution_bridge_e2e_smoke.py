from __future__ import annotations

import asyncio
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
from app.interfaces.api.qa_dispatch_bridge_worker import BridgeExecutionResult
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.storage import Storage


class _FakeMetricsPort:
    def increment(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)

    def observe_ms(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)


class _DummyCipher:
    def decrypt(self, encrypted_token: str) -> str:
        return str(encrypted_token)


class LTC82Stage5ExecutionBridgeE2ESmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        if _IMPORT_ERROR is not None:
            self.skipTest(f"fastapi/pydantic deps are unavailable: {_IMPORT_ERROR}")
        try:
            from app.interfaces.api.read_only_app import build_read_only_fastapi_app as builder
        except Exception as exc:
            self.skipTest(f"api transport dependencies are unavailable: {exc}")
        self._builder = builder

    def test_post_question_progresses_to_answered_via_in_process_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "ltc82.sqlite3"
            storage = Storage(db_path)
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9820, "e2e-bridge")
                role = storage.upsert_role(
                    role_name="dev",
                    description="e2e",
                    base_system_prompt="sp",
                    extra_instruction="ei",
                    llm_model=None,
                    is_active=True,
                )
                storage.ensure_group_role(group.group_id, role.role_id)

            async def _bridge_exec(_runtime, question, _correlation_id):
                return BridgeExecutionResult(
                    answer_text=f"echo:{question.text}",
                    role_name="dev",
                    answer_team_role_id=question.target_team_role_id,
                    append_orchestrator_feed=True,
                )

            runtime = SimpleNamespace(
                storage=storage,
                role_runtime_status_service=RoleRuntimeStatusService(storage, free_transition_delay_sec=0),
                role_dispatch_queue_service=SimpleNamespace(),
                free_transition_delay_sec=0,
                authz_service=OwnerOnlyAuthzService(owner_user_id=700),
                metrics_port=_FakeMetricsPort(),
                # Required for bridge worker wiring (executor is overridden).
                cipher=_DummyCipher(),
                llm_executor=object(),
                session_resolver=object(),
                qa_dispatch_bridge_execute_question_fn=_bridge_exec,
            )
            app = self._builder(runtime)
            with TestClient(app) as client:
                teams = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "700"})
                self.assertEqual(teams.status_code, 200)
                team_id = int(teams.json()["items"][0]["team_id"])
                roles = client.get(f"/api/v1/teams/{team_id}/roles", headers={"X-Owner-User-Id": "700"})
                role_id = int(roles.json()[0]["role_id"])
                team_role_id = int(storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)
                self.assertGreater(team_role_id, 0)

                create = client.post(
                    "/api/v1/questions",
                    headers={"X-Owner-User-Id": "700", "Idempotency-Key": "stage5-bridge-e2e-k1"},
                    json={
                        "team_id": team_id,
                        "created_by_user_id": 700,
                        "text": "bridge question",
                        "team_role_id": team_role_id,
                        "question_id": "q-bridge-e2e",
                        "thread_id": "t-bridge-e2e",
                    },
                )
                self.assertEqual(create.status_code, 202)

                status_payload = None
                for _ in range(80):
                    status_response = client.get(
                        "/api/v1/questions/q-bridge-e2e/status",
                        headers={"X-Owner-User-Id": "700"},
                    )
                    self.assertEqual(status_response.status_code, 200)
                    status_payload = status_response.json()
                    if status_payload.get("status") == "answered":
                        break
                    asyncio.run(asyncio.sleep(0.05))

                self.assertIsNotNone(status_payload)
                self.assertEqual(status_payload.get("status"), "answered")

                answer = client.get(
                    "/api/v1/questions/q-bridge-e2e/answer",
                    headers={"X-Owner-User-Id": "700"},
                )
                self.assertEqual(answer.status_code, 200)
                self.assertIn("echo:bridge question", answer.json().get("text", ""))


if __name__ == "__main__":
    unittest.main()
