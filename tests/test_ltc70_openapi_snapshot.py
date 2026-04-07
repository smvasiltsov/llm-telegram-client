from __future__ import annotations

import json
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


class LTC70OpenApiSnapshotTests(unittest.TestCase):
    SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "read_only_openapi_snapshot.json"

    def setUp(self) -> None:
        if _IMPORT_ERROR is not None:
            self.skipTest(f"openapi snapshot deps are unavailable: {_IMPORT_ERROR}")
        try:
            from app.interfaces.api.read_only_app import build_read_only_fastapi_app as builder
        except Exception as exc:
            self.skipTest(f"api transport dependencies are unavailable: {exc}")
        self._builder = builder

    def _client(self) -> TestClient:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        storage = Storage(Path(td.name) / "ltc70_api.sqlite3")
        with storage.transaction(immediate=True):
            group = storage.upsert_group(-9701, "g")
            role = storage.upsert_role(
                role_name="dev",
                description="d",
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
        return TestClient(app)

    def test_read_only_openapi_snapshot(self) -> None:
        client = self._client()
        schema = client.get("/openapi.json").json()
        managed_statuses = {"200", "204", "401", "403", "404", "409", "422", "500"}
        managed_routes: dict[str, tuple[str, ...]] = {
            "/api/v1/answers/{answer_id}": ("get",),
            "/api/v1/orchestrator/feed": ("get",),
            "/api/v1/post_processing_tools": ("get",),
            "/api/v1/pre_processing_tools": ("get",),
            "/api/v1/questions": ("post",),
            "/api/v1/questions/{question_id}": ("get",),
            "/api/v1/questions/{question_id}/answer": ("get",),
            "/api/v1/questions/{question_id}/status": ("get",),
            "/api/v1/qa-journal": ("get",),
            "/api/v1/roles/{role_id}": ("patch",),
            "/api/v1/roles/catalog": ("get",),
            "/api/v1/roles/catalog/errors": ("get",),
            "/api/v1/skills": ("get",),
            "/api/v1/threads/{thread_id}": ("get",),
            "/api/v1/teams": ("get",),
            "/api/v1/teams/{team_id}/roles": ("get",),
            "/api/v1/teams/{team_id}/roles/{role_id}": ("patch", "delete"),
            "/api/v1/teams/{team_id}/roles/{role_id}/reset-session": ("post",),
            "/api/v1/teams/{team_id}/runtime-status": ("get",),
            "/api/v1/teams/{team_id}/sessions": ("get",),
            "/api/v1/team-roles/{team_role_id}/skills/{skill_id}": ("put",),
            "/api/v1/team-roles/{team_role_id}/prepost/{prepost_id}": ("put",),
        }
        summary = {
            "paths": sorted(
                [
                    path
                    for path in schema.get("paths", {}).keys()
                    if path in managed_routes
                ]
            ),
            "responses": {},
        }
        for path in summary["paths"]:
            summary["responses"][path] = {}
            for method in managed_routes[path]:
                operation = schema["paths"][path].get(method)
                if not operation:
                    continue
                statuses = sorted(code for code in operation.get("responses", {}).keys() if code in managed_statuses)
                summary["responses"][path][method] = statuses

        expected = json.loads(self.SNAPSHOT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(summary, expected)


if __name__ == "__main__":
    unittest.main()
