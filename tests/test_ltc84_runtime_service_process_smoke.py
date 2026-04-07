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
from app.application.use_cases.qa_runtime_bridge_core import BridgeExecutionResult
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


class LTC84RuntimeServiceProcessSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        if _IMPORT_ERROR is not None:
            self.skipTest(f"fastapi/pydantic deps are unavailable: {_IMPORT_ERROR}")
        try:
            from app.interfaces.runtime.runtime_service_app import (
                build_runtime_service_fastapi_app as builder,
            )
        except Exception as exc:
            self.skipTest(f"runtime service transport deps are unavailable: {exc}")
        self._builder = builder

    def test_runtime_service_starts_worker_and_processes_questions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "ltc84.sqlite3"
            storage = Storage(db_path)
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9840, "runtime-svc")
                role = storage.upsert_role(
                    role_name="dev",
                    description="runtime service",
                    base_system_prompt="sp",
                    extra_instruction="ei",
                    llm_model=None,
                    is_active=True,
                )
                storage.ensure_group_role(group.group_id, role.role_id)
                team_id = int(group.team_id or 0)
                team_role_id = int(storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True) or 0)
                storage.create_question(
                    question_id="q-runtime-svc-1",
                    thread_id="t-runtime-svc-1",
                    team_id=team_id,
                    created_by_user_id=700,
                    target_team_role_id=team_role_id,
                    text="runtime service question",
                    status="accepted",
                )

            async def _bridge_exec(_runtime, question, _correlation_id):
                return BridgeExecutionResult(
                    answer_text=f"bridge:{question.text}",
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
                cipher=_DummyCipher(),
                llm_executor=object(),
                session_resolver=object(),
                dispatch_mode="single-instance",
                dispatch_is_runner=True,
                queue_backend="in-memory",
                started_at="2026-04-06T00:00:00+00:00",
                qa_dispatch_bridge_execute_question_fn=_bridge_exec,
            )
            app = self._builder(runtime)
            with TestClient(app) as client:
                live = client.get("/health/live")
                self.assertEqual(live.status_code, 200)
                self.assertEqual(live.json().get("status"), "ok")

                ready = client.get("/health/ready")
                self.assertEqual(ready.status_code, 200)
                self.assertEqual(ready.json().get("status"), "ready")

                health = client.get("/runtime/dispatch-health", headers={"X-Owner-User-Id": "700"})
                self.assertEqual(health.status_code, 200)
                payload = health.json()
                self.assertEqual(payload.get("mode"), "single-instance")
                self.assertTrue(bool(payload.get("worker", {}).get("enabled")))
                self.assertTrue(bool(payload.get("worker", {}).get("is_running")))

                status = None
                for _ in range(80):
                    status = storage.get_question("q-runtime-svc-1")
                    if status is not None and status.status == "answered":
                        break
                    asyncio.run(asyncio.sleep(0.05))
                self.assertIsNotNone(status)
                self.assertEqual(status.status if status else None, "answered")
                answer = storage.get_latest_answer_for_question("q-runtime-svc-1")
                self.assertIsNotNone(answer)
                self.assertIn("bridge:runtime service question", answer.text if answer else "")

    def test_runtime_service_ready_is_not_ready_on_non_runner(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "ltc84_non_runner.sqlite3")
            runtime = SimpleNamespace(
                storage=storage,
                role_runtime_status_service=RoleRuntimeStatusService(storage, free_transition_delay_sec=0),
                role_dispatch_queue_service=SimpleNamespace(),
                free_transition_delay_sec=0,
                authz_service=OwnerOnlyAuthzService(owner_user_id=700),
                metrics_port=_FakeMetricsPort(),
                cipher=_DummyCipher(),
                llm_executor=object(),
                session_resolver=object(),
                dispatch_mode="single-runner",
                dispatch_is_runner=False,
                queue_backend="in-memory",
                started_at="2026-04-06T00:00:00+00:00",
            )
            app = self._builder(runtime)
            with TestClient(app) as client:
                ready = client.get("/health/ready")
                self.assertEqual(ready.status_code, 503)
                self.assertEqual(ready.json().get("status"), "not_ready")

                health = client.get("/runtime/dispatch-health", headers={"X-Owner-User-Id": "700"})
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.json().get("mode"), "single-runner")
                self.assertFalse(bool(health.json().get("worker", {}).get("enabled")))


if __name__ == "__main__":
    unittest.main()
