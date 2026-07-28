from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.application.authz import OwnerOnlyAuthzService
from app.services.plan_supervisor import PlanStepInput, PlanSupervisorService
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.storage import Storage

_IMPORT_ERROR: Exception | None = None
try:
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover
    _IMPORT_ERROR = exc


class PlanSupervisorApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        if _IMPORT_ERROR is not None:
            self.skipTest(f"fastapi test dependencies unavailable: {_IMPORT_ERROR}")
        from app.interfaces.api.read_only_app import build_read_only_fastapi_app

        self._builder = build_read_only_fastapi_app

    def _client(self, *, enabled: bool) -> TestClient:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        storage = Storage(Path(td.name) / "plan-supervisor-api.sqlite3")
        with storage.transaction(immediate=True):
            group = storage.upsert_group(-9301, "api")
        team_id = int(group.team_id or 0)
        if enabled:
            service = PlanSupervisorService(storage)
            created = service.start_plan(
                team_id=team_id,
                thread_id="thr-api",
                goal="Goal",
                steps=[PlanStepInput(step_id="s1", title="One")],
                actor_role="codex",
                created_by_user_id=700,
            )
            plan_run_id = str(created["plan_run"]["plan_run_id"])
        else:
            plan_run_id = "plan_missing"

        runtime = SimpleNamespace(
            storage=storage,
            role_runtime_status_service=RoleRuntimeStatusService(storage, free_transition_delay_sec=0),
            role_dispatch_queue_service=SimpleNamespace(),
            free_transition_delay_sec=0,
            authz_service=OwnerOnlyAuthzService(owner_user_id=700),
            metrics_port=SimpleNamespace(increment=lambda *a, **k: None, observe_ms=lambda *a, **k: None),
            role_catalog=SimpleNamespace(),
            skills_registry=SimpleNamespace(),
            prepost_processing_registry=SimpleNamespace(),
            provider_registry={},
            dispatch_mode="single-instance",
            dispatch_is_runner=True,
            queue_backend="in-memory",
            started_at="2026-05-02T00:00:00+00:00",
        )
        app = self._builder(runtime)
        client = TestClient(app)
        client.plan_run_id = plan_run_id  # type: ignore[attr-defined]
        return client

    def _report_step_with_string_artifact(self, client: TestClient) -> str:
        plan_run_id = str(client.plan_run_id)  # type: ignore[attr-defined]
        storage = client.app.state.runtime.storage
        service = PlanSupervisorService(storage)
        service.report_step(
            plan_run_id=plan_run_id,
            step_id="s1",
            summary="done",
            artifacts=["/opt/projects/example/docs/spec.md"],
            test_commands=["pytest -q"],
            actor_id="codex",
        )
        return plan_run_id

    def test_plan_view_requires_owner_and_returns_cors(self) -> None:
        client = self._client(enabled=True)
        plan_run_id = client.plan_run_id  # type: ignore[attr-defined]

        unauth = client.get(f"/api/v1/plan-runs/{plan_run_id}/view")
        self.assertEqual(unauth.status_code, 401)

        forbidden = client.get(f"/api/v1/plan-runs/{plan_run_id}/view", headers={"X-Owner-User-Id": "701"})
        self.assertEqual(forbidden.status_code, 403)

        ok = client.get(
            f"/api/v1/plan-runs/{plan_run_id}/view",
            headers={"X-Owner-User-Id": "700", "Origin": "app://obsidian.md"},
        )
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.headers.get("access-control-allow-origin"), "app://obsidian.md")
        self.assertIn("ui", ok.json())

    def test_plan_endpoints_respect_feature_flag(self) -> None:
        client = self._client(enabled=False)
        resp = client.get("/api/v1/plan-runs/plan_any/view", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(resp.status_code, 404)

    def test_list_active_plan_runs_with_optional_team_role_filter(self) -> None:
        client = self._client(enabled=True)
        plan_run_id = client.plan_run_id  # type: ignore[attr-defined]

        created = client.get(
            f"/api/v1/plan-runs/{plan_run_id}",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(created.status_code, 200)
        team_id = int(created.json()["team_id"])

        listed = client.get(
            f"/api/v1/plan-runs?team_id={team_id}",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(listed.status_code, 200)
        payload = listed.json()
        self.assertTrue(any(str(item.get("plan_run_id")) == str(plan_run_id) for item in payload))

        filtered_ok = client.get(
            f"/api/v1/plan-runs?team_id={team_id}&team_role=codex",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(filtered_ok.status_code, 200)
        self.assertTrue(any(str(item.get("plan_run_id")) == str(plan_run_id) for item in filtered_ok.json()))

        filtered_empty = client.get(
            f"/api/v1/plan-runs?team_id={team_id}&team_role=unknown_role",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(filtered_empty.status_code, 200)
        self.assertEqual(filtered_empty.json(), [])

    def test_plan_run_steps_accept_string_artifacts(self) -> None:
        client = self._client(enabled=True)
        plan_run_id = self._report_step_with_string_artifact(client)

        response = client.get(
            f"/api/v1/plan-runs/{plan_run_id}/steps",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload[0]["artifacts"], ["/opt/projects/example/docs/spec.md"])
        self.assertEqual(payload[0]["test_commands"], ["pytest -q"])

    def test_plan_run_view_accepts_string_artifacts(self) -> None:
        client = self._client(enabled=True)
        plan_run_id = self._report_step_with_string_artifact(client)

        response = client.get(
            f"/api/v1/plan-runs/{plan_run_id}/view",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["steps"][0]["artifacts"], ["/opt/projects/example/docs/spec.md"])
        self.assertEqual(payload["steps"][0]["test_commands"], ["pytest -q"])

    def test_delete_plan_run_removes_plan_and_returns_404_afterwards(self) -> None:
        client = self._client(enabled=True)
        plan_run_id = str(client.plan_run_id)  # type: ignore[attr-defined]

        deleted = client.request(
            "DELETE",
            f"/api/v1/plan-runs/{plan_run_id}",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(deleted.status_code, 204)

        get_run = client.get(
            f"/api/v1/plan-runs/{plan_run_id}",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(get_run.status_code, 404)

        get_steps = client.get(
            f"/api/v1/plan-runs/{plan_run_id}/steps",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(get_steps.status_code, 404)

    def test_delete_plan_run_missing_returns_404(self) -> None:
        client = self._client(enabled=False)
        response = client.request(
            "DELETE",
            "/api/v1/plan-runs/plan_missing",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
