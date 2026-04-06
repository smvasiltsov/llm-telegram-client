from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_IMPORT_ERROR: Exception | None = None
try:
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover - dependency gap in environment
    _IMPORT_ERROR = exc

from app.application.authz import OwnerOnlyAuthzService
from app.role_catalog import RoleCatalog
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.storage import Storage


class _FakeMetricsPort:
    def __init__(self) -> None:
        self.increments: list[tuple[str, dict[str, str], int]] = []
        self.observations: list[tuple[str, float, dict[str, str]]] = []

    def increment(self, name: str, *, labels=None, value: int = 1) -> None:  # noqa: ANN001
        self.increments.append((name, dict(labels or {}), int(value)))

    def observe_ms(self, name: str, *, value_ms: float, labels=None) -> None:  # noqa: ANN001
        self.observations.append((name, float(value_ms), dict(labels or {})))

    def operation_timer(self, operation: str, *, transport: str):  # noqa: ANN001
        _ = (operation, transport)
        return None


class LTC69ReadOnlyFastApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        if _IMPORT_ERROR is not None:
            self.skipTest(f"fastapi test dependencies are unavailable: {_IMPORT_ERROR}")
        try:
            from app.interfaces.api.read_only_app import build_read_only_fastapi_app as builder
        except Exception as exc:
            self.skipTest(f"api transport dependencies are unavailable: {exc}")
        self._builder = builder

    def _client(self) -> TestClient:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        catalog_dir = root / "roles"
        catalog_dir.mkdir(parents=True, exist_ok=True)
        (catalog_dir / "dev.json").write_text(
            (
                '{"schema_version":1,"role_name":"dev","description":"Developer",'
                '"base_system_prompt":"p","extra_instruction":"i","llm_model":"gpt","is_active":true}\n'
            ),
            encoding="utf-8",
        )
        (catalog_dir / "ops.json").write_text(
            (
                '{"schema_version":1,"role_name":"ops","description":"Ops",'
                '"base_system_prompt":"p","extra_instruction":"i","llm_model":"gpt","is_active":false}\n'
            ),
            encoding="utf-8",
        )
        (catalog_dir / "broken.json").write_text("{", encoding="utf-8")
        role_catalog = RoleCatalog.load(catalog_dir)
        storage = Storage(root / "ltc69_api.sqlite3")
        storage.attach_role_catalog(role_catalog)
        with storage.transaction(immediate=True):
            group = storage.upsert_group(-9692, "g")
            role = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            storage.set_team_role_mode(int(group.team_id or 0), role.role_id, "orchestrator")
            storage.save_user_role_session_by_team(
                telegram_user_id=700,
                team_id=int(group.team_id or 0),
                role_id=role.role_id,
                session_id="session-dev-1",
            )
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
            metrics_port=_FakeMetricsPort(),
            role_catalog=role_catalog,
        )
        app = self._builder(runtime)
        return TestClient(app)

    def test_get_teams_returns_team_list(self) -> None:
        client = self._client()
        response = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsInstance(payload, dict)
        self.assertIn("items", payload)
        self.assertIn("meta", payload)
        self.assertTrue(payload["items"])
        self.assertIn("team_id", payload["items"][0])
        self.assertGreaterEqual(payload["meta"]["total"], payload["meta"]["returned"])

    def test_get_team_roles_returns_role_list(self) -> None:
        client = self._client()
        teams = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "700"}).json()
        team_id = int(teams["items"][0]["team_id"])
        response = client.get(f"/api/v1/teams/{team_id}/roles", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsInstance(payload, list)
        self.assertTrue(any(item["role_name"] == "dev" for item in payload))
        self.assertTrue(any(item.get("is_orchestrator") is True for item in payload))

    def test_get_team_roles_include_inactive_returns_disabled_or_inactive(self) -> None:
        client = self._client()
        teams = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "700"}).json()
        team_id = int(teams["items"][0]["team_id"])
        with client.app.state.runtime.storage.transaction(immediate=True):
            team = client.app.state.runtime.storage.get_team(team_id)
            ops = client.app.state.runtime.storage.upsert_role(
                role_name="ops",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            client.app.state.runtime.storage.bind_master_role_to_team(team.team_id, ops.role_id)
            client.app.state.runtime.storage.set_team_role_enabled(team.team_id, ops.role_id, False)
        response = client.get(
            f"/api/v1/teams/{team_id}/roles?include_inactive=true",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(any(item["role_name"] == "ops" and item["is_active"] is False for item in payload))

    def test_get_team_runtime_status_returns_status_list(self) -> None:
        client = self._client()
        teams = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "700"}).json()
        team_id = int(teams["items"][0]["team_id"])
        response = client.get(f"/api/v1/teams/{team_id}/runtime-status", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsInstance(payload, list)
        self.assertIn("status", payload[0])

    def test_missing_team_returns_unified_error_shape(self) -> None:
        client = self._client()
        response = client.get("/api/v1/teams/999999/roles", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "storage.not_found")
        self.assertIn("message", payload["error"])

    def test_owner_authz_missing_credentials_returns_401(self) -> None:
        client = self._client()
        response = client.get("/api/v1/teams")
        self.assertEqual(response.status_code, 401)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "auth.unauthorized")
        self.assertIsInstance(payload["error"]["details"].get("correlation_id"), str)

    def test_owner_authz_non_owner_returns_403(self) -> None:
        client = self._client()
        response = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "701"})
        self.assertEqual(response.status_code, 403)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "auth.unauthorized")

    def test_get_teams_supports_limit_offset_metadata(self) -> None:
        client = self._client()
        response = client.get("/api/v1/teams?limit=1&offset=0", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["meta"]["limit"], 1)
        self.assertEqual(payload["meta"]["offset"], 0)
        self.assertLessEqual(payload["meta"]["returned"], 1)

    def test_get_roles_catalog_returns_paged_items(self) -> None:
        client = self._client()
        response = client.get("/api/v1/roles/catalog?limit=10&offset=0", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("items", payload)
        self.assertIn("meta", payload)
        self.assertTrue(any(item["role_name"] == "dev" for item in payload["items"]))
        self.assertTrue(all(item["is_active"] is True for item in payload["items"]))

    def test_get_roles_catalog_include_inactive_returns_inactive(self) -> None:
        client = self._client()
        response = client.get("/api/v1/roles/catalog?include_inactive=true", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(any(item["role_name"] == "ops" and item["is_active"] is False for item in payload["items"]))

    def test_get_roles_catalog_errors_returns_issue_items(self) -> None:
        client = self._client()
        response = client.get("/api/v1/roles/catalog/errors", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsInstance(payload, list)
        self.assertTrue(any(item["code"] == "invalid_json" for item in payload))

    def test_get_team_sessions_returns_paged_items(self) -> None:
        client = self._client()
        teams = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "700"}).json()
        team_id = int(teams["items"][0]["team_id"])
        response = client.get(f"/api/v1/teams/{team_id}/sessions", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("items", payload)
        self.assertIn("meta", payload)
        self.assertTrue(payload["items"])
        self.assertIn("telegram_user_id", payload["items"][0])
        self.assertIn("session_id", payload["items"][0])

    def test_new_endpoints_missing_owner_return_401_with_error_envelope(self) -> None:
        client = self._client()
        endpoints = (
            "/api/v1/roles/catalog",
            "/api/v1/roles/catalog/errors",
            "/api/v1/teams/1/sessions",
        )
        for path in endpoints:
            response = client.get(path)
            self.assertEqual(response.status_code, 401)
            payload = response.json()
            self.assertEqual(payload["error"]["code"], "auth.unauthorized")
            self.assertIn("message", payload["error"])

    def test_new_endpoints_non_owner_return_403_with_error_envelope(self) -> None:
        client = self._client()
        endpoints = (
            "/api/v1/roles/catalog",
            "/api/v1/roles/catalog/errors",
            "/api/v1/teams/1/sessions",
        )
        for path in endpoints:
            response = client.get(path, headers={"X-Owner-User-Id": "701"})
            self.assertEqual(response.status_code, 403)
            payload = response.json()
            self.assertEqual(payload["error"]["code"], "auth.unauthorized")
            self.assertIn("message", payload["error"])

    def test_team_sessions_missing_team_returns_unified_error_shape(self) -> None:
        client = self._client()
        response = client.get("/api/v1/teams/999999/sessions", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "storage.not_found")
        self.assertIn("message", payload["error"])

    def test_response_contains_generated_correlation_id(self) -> None:
        client = self._client()
        response = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 200)
        correlation_id = response.headers.get("X-Correlation-Id")
        self.assertIsInstance(correlation_id, str)
        self.assertTrue(correlation_id)

    def test_response_propagates_incoming_correlation_id(self) -> None:
        client = self._client()
        response = client.get(
            "/api/v1/teams",
            headers={"X-Owner-User-Id": "700", "X-Correlation-Id": "corr-abc-123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Correlation-Id"), "corr-abc-123")

    def test_api_metrics_emitted_for_http_request(self) -> None:
        client = self._client()
        _ = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "700"})
        metrics = client.app.state.runtime.metrics_port
        increments = [item for item in metrics.increments if item[0] == "api_http_requests_total"]
        observations = [item for item in metrics.observations if item[0] == "api_http_request_latency_ms"]
        stage4_increments = [item for item in metrics.increments if item[0] == "http_requests_total"]
        stage4_observations = [item for item in metrics.observations if item[0] == "http_request_duration_ms"]
        self.assertTrue(increments)
        self.assertTrue(observations)
        self.assertTrue(stage4_increments)
        self.assertTrue(stage4_observations)
        self.assertIn("operation", increments[0][1])
        self.assertIn("result", increments[0][1])
        self.assertEqual(increments[0][1].get("transport"), "http")
        self.assertEqual(stage4_increments[0][1].get("method"), "GET")
        self.assertEqual(stage4_increments[0][1].get("route"), "/api/v1/teams")


if __name__ == "__main__":
    unittest.main()
