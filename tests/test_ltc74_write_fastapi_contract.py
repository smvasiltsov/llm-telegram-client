from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.application.contracts import ErrorCode, Result
from app.application.authz import OwnerOnlyAuthzService
from app.role_catalog import RoleCatalog
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.storage import Storage

_IMPORT_ERROR: Exception | None = None
try:
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover - dependency gap in environment
    _IMPORT_ERROR = exc


class _FakeMetricsPort:
    def increment(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)

    def observe_ms(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)

    def operation_timer(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)
        return None


class _FakeSkillsRegistry:
    def __init__(self) -> None:
        self._known = {"fs.list_dir": object()}

    def get(self, skill_id: str):
        return self._known.get(skill_id)


class _FakePrepostRegistry:
    def __init__(self) -> None:
        self._known = {"echo": object()}

    def get(self, prepost_id: str):
        return self._known.get(prepost_id)


class LTC74WriteFastApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        if _IMPORT_ERROR is not None:
            self.skipTest(f"fastapi test dependencies are unavailable: {_IMPORT_ERROR}")
        try:
            from app.interfaces.api.read_only_app import build_read_only_fastapi_app as builder
        except Exception as exc:
            self.skipTest(f"api transport dependencies are unavailable: {exc}")
        self._builder = builder

    def _client(self, *, dispatch_mode: str = "single-instance", dispatch_is_runner: bool = True) -> TestClient:
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
        role_catalog = RoleCatalog.load(catalog_dir)
        storage = Storage(root / "ltc74_api.sqlite3")
        storage.attach_role_catalog(role_catalog)
        with storage.transaction(immediate=True):
            group = storage.upsert_group(-9741, "g")
            role = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            team_role, _ = storage.bind_master_role_to_team(int(group.team_id or 0), role.role_id)
            if team_role.team_role_id is None:
                raise AssertionError("team_role_id missing")
            storage.save_user_role_session_by_team_role(telegram_user_id=700, team_role_id=team_role.team_role_id, session_id="s-1")
        runtime = SimpleNamespace(
            storage=storage,
            role_runtime_status_service=RoleRuntimeStatusService(storage, free_transition_delay_sec=0),
            role_dispatch_queue_service=SimpleNamespace(),
            free_transition_delay_sec=0,
            authz_service=OwnerOnlyAuthzService(owner_user_id=700),
            metrics_port=_FakeMetricsPort(),
            role_catalog=role_catalog,
            skills_registry=_FakeSkillsRegistry(),
            prepost_processing_registry=_FakePrepostRegistry(),
            provider_registry={},
            dispatch_mode=dispatch_mode,
            dispatch_is_runner=dispatch_is_runner,
            queue_backend="in-memory",
            started_at="2026-04-05T00:00:00+00:00",
        )
        app = self._builder(runtime)
        return TestClient(app)

    def _team_and_role(self, client: TestClient) -> tuple[int, int, int]:
        teams = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "700"}).json()
        team_id = int(teams["items"][0]["team_id"])
        roles = client.get(f"/api/v1/teams/{team_id}/roles", headers={"X-Owner-User-Id": "700"}).json()
        role_id = int(roles[0]["role_id"])
        team_role_id = int(client.app.state.runtime.storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)
        return team_id, role_id, team_role_id

    def test_patch_team_role_returns_200(self) -> None:
        client = self._client()
        _, _, team_role_id = self._team_and_role(client)
        response = client.patch(
            f"/api/v1/team-roles/{team_role_id}",
            headers={"X-Owner-User-Id": "700"},
            json={"enabled": False, "display_name": "DevX"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["enabled"])
        self.assertEqual(body["display_name"], "DevX")

    def test_patch_team_role_accepts_is_active_alias(self) -> None:
        client = self._client()
        _, _, team_role_id = self._team_and_role(client)
        response = client.patch(
            f"/api/v1/team-roles/{team_role_id}",
            headers={"X-Owner-User-Id": "700"},
            json={"is_active": False},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["is_active"])
        self.assertFalse(body["enabled"])

    def test_reset_session_returns_200_and_is_idempotent(self) -> None:
        client = self._client()
        team_id, role_id, team_role_id = self._team_and_role(client)
        with client.app.state.runtime.storage.transaction(immediate=True):
            client.app.state.runtime.storage.set_team_role_working_dir_by_id(team_role_id, "/tmp/work")
            client.app.state.runtime.storage.set_team_role_root_dir_by_id(team_role_id, "/tmp/root")
        path = f"/api/v1/team-roles/{team_role_id}/reset-session"
        payload = {"telegram_user_id": 700}
        r1 = client.post(path, headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-r1"}, json=payload)
        r2 = client.post(path, headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-r1"}, json=payload)
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json()["operation"], "reset_session")
        role_state = client.app.state.runtime.storage.get_team_role(team_id, role_id)
        self.assertIsNone(role_state.working_dir)
        self.assertIsNone(role_state.root_dir)

    def test_reset_session_returns_404_for_invalid_telegram_user_id(self) -> None:
        client = self._client()
        _, _, team_role_id = self._team_and_role(client)
        response = client.post(
            f"/api/v1/team-roles/{team_role_id}/reset-session",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-r-missing-user"},
            json={"telegram_user_id": 999999},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "storage.not_found")

    def test_delete_deactivate_returns_204(self) -> None:
        client = self._client()
        team_id, role_id, team_role_id = self._team_and_role(client)
        response = client.request(
            "DELETE",
            f"/api/v1/team-roles/{team_role_id}",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-d1"},
            json={"telegram_user_id": 700},
        )
        self.assertEqual(response.status_code, 204)
        with self.assertRaises(ValueError):
            _ = client.app.state.runtime.storage.get_team_role(team_id, role_id)

    def test_team_roles_include_inactive_returns_only_added_roles_and_respects_is_active(self) -> None:
        client = self._client()
        team_id, _, team_role_id = self._team_and_role(client)

        disabled = client.patch(
            f"/api/v1/team-roles/{team_role_id}",
            headers={"X-Owner-User-Id": "700"},
            json={"is_active": False},
        )
        self.assertEqual(disabled.status_code, 200)

        active_only = client.get(f"/api/v1/teams/{team_id}/roles", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(active_only.status_code, 200)
        self.assertEqual(active_only.json(), [])

        with_inactive = client.get(
            f"/api/v1/teams/{team_id}/roles?include_inactive=true",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(with_inactive.status_code, 200)
        self.assertEqual(len(with_inactive.json()), 1)
        self.assertFalse(with_inactive.json()[0]["is_active"])

        deleted = client.request(
            "DELETE",
            f"/api/v1/team-roles/{team_role_id}",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-d2"},
            json={"telegram_user_id": 700},
        )
        self.assertEqual(deleted.status_code, 204)

        after_delete = client.get(
            f"/api/v1/teams/{team_id}/roles?include_inactive=true",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(after_delete.status_code, 200)
        self.assertEqual(after_delete.json(), [])

    def test_put_skill_returns_200(self) -> None:
        client = self._client()
        _, _, team_role_id = self._team_and_role(client)
        response = client.put(
            f"/api/v1/team-roles/{team_role_id}/skills/fs.list_dir",
            headers={"X-Owner-User-Id": "700"},
            json={"enabled": True, "config": {"root_dir": "/tmp"}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["enabled"])

    def test_put_prepost_returns_200(self) -> None:
        client = self._client()
        _, _, team_role_id = self._team_and_role(client)
        response = client.put(
            f"/api/v1/team-roles/{team_role_id}/prepost/echo",
            headers={"X-Owner-User-Id": "700"},
            json={"enabled": True, "config": {"x": 1}},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["enabled"])

    def test_put_working_dir_returns_200(self) -> None:
        client = self._client()
        _, _, team_role_id = self._team_and_role(client)
        response = client.put(
            f"/api/v1/team-roles/{team_role_id}/working-dir",
            headers={"X-Owner-User-Id": "700"},
            json={"working_dir": "/tmp/work"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["team_role_id"], team_role_id)
        self.assertEqual(body["working_dir"], "/tmp/work")

    def test_put_root_dir_returns_200(self) -> None:
        client = self._client()
        _, _, team_role_id = self._team_and_role(client)
        response = client.put(
            f"/api/v1/team-roles/{team_role_id}/root-dir",
            headers={"X-Owner-User-Id": "700"},
            json={"root_dir": "/tmp/root"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["team_role_id"], team_role_id)
        self.assertEqual(body["root_dir"], "/tmp/root")

    def test_owner_authz_401_for_write_endpoints(self) -> None:
        client = self._client()
        team_id, role_id, team_role_id = self._team_and_role(client)
        checks = [
            ("patch", f"/api/v1/team-roles/{team_role_id}", {"enabled": False}),
            ("post", f"/api/v1/team-roles/{team_role_id}/reset-session", {"telegram_user_id": 700}),
            ("delete", f"/api/v1/team-roles/{team_role_id}", {"telegram_user_id": 700}),
            ("put", f"/api/v1/team-roles/{team_role_id}/skills/fs.list_dir", {"enabled": True}),
            ("put", f"/api/v1/team-roles/{team_role_id}/working-dir", {"working_dir": "/tmp/work"}),
            ("put", f"/api/v1/team-roles/{team_role_id}/root-dir", {"root_dir": "/tmp/root"}),
            ("put", f"/api/v1/team-roles/{team_role_id}/prepost/echo", {"enabled": True}),
        ]
        for method, path, payload in checks:
            headers = {}
            if method in {"post", "delete"}:
                headers["Idempotency-Key"] = "idem-authz"
            response = client.request(method.upper(), path, headers=headers, json=payload)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"]["code"], "auth.unauthorized")

    def test_owner_authz_403_for_write_endpoints(self) -> None:
        client = self._client()
        team_id, role_id, team_role_id = self._team_and_role(client)
        checks = [
            ("patch", f"/api/v1/team-roles/{team_role_id}", {"enabled": False}),
            ("post", f"/api/v1/team-roles/{team_role_id}/reset-session", {"telegram_user_id": 700}),
            ("delete", f"/api/v1/team-roles/{team_role_id}", {"telegram_user_id": 700}),
            ("put", f"/api/v1/team-roles/{team_role_id}/skills/fs.list_dir", {"enabled": True}),
            ("put", f"/api/v1/team-roles/{team_role_id}/working-dir", {"working_dir": "/tmp/work"}),
            ("put", f"/api/v1/team-roles/{team_role_id}/root-dir", {"root_dir": "/tmp/root"}),
            ("put", f"/api/v1/team-roles/{team_role_id}/prepost/echo", {"enabled": True}),
        ]
        for method, path, payload in checks:
            headers = {"X-Owner-User-Id": "701"}
            if method in {"post", "delete"}:
                headers["Idempotency-Key"] = "idem-authz"
            response = client.request(method.upper(), path, headers=headers, json=payload)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], "auth.unauthorized")

    def test_write_endpoints_return_404_not_found(self) -> None:
        client = self._client()
        headers = {"X-Owner-User-Id": "700"}
        patch_404 = client.patch("/api/v1/team-roles/999999", headers=headers, json={"enabled": False})
        reset_404 = client.post(
            "/api/v1/team-roles/999999/reset-session",
            headers={**headers, "Idempotency-Key": "idem-404"},
            json={"telegram_user_id": 700},
        )
        delete_404 = client.request(
            "DELETE",
            "/api/v1/team-roles/999999",
            headers={**headers, "Idempotency-Key": "idem-404"},
            json={"telegram_user_id": 700},
        )
        skill_404 = client.put("/api/v1/team-roles/999999/skills/fs.list_dir", headers=headers, json={"enabled": True})
        working_404 = client.put("/api/v1/team-roles/999999/working-dir", headers=headers, json={"working_dir": "/tmp/work"})
        root_404 = client.put("/api/v1/team-roles/999999/root-dir", headers=headers, json={"root_dir": "/tmp/root"})
        prepost_404 = client.put("/api/v1/team-roles/999999/prepost/echo", headers=headers, json={"enabled": True})
        for response in (patch_404, reset_404, delete_404, skill_404, working_404, root_404, prepost_404):
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["error"]["code"], "storage.not_found")

    def test_write_endpoints_return_422_validation(self) -> None:
        client = self._client()
        _, _, team_role_id = self._team_and_role(client)
        patch_422 = client.patch(f"/api/v1/team-roles/{team_role_id}", headers={"X-Owner-User-Id": "700"}, json={})
        reset_422 = client.post(
            f"/api/v1/team-roles/{team_role_id}/reset-session",
            headers={"X-Owner-User-Id": "700"},
            json={"telegram_user_id": 700},
        )
        delete_422 = client.request(
            "DELETE",
            f"/api/v1/team-roles/{team_role_id}",
            headers={"X-Owner-User-Id": "700"},
            json={"telegram_user_id": 700},
        )
        working_422 = client.put(
            f"/api/v1/team-roles/{team_role_id}/working-dir",
            headers={"X-Owner-User-Id": "700"},
            json={"working_dir": "relative/path"},
        )
        root_422 = client.put(
            f"/api/v1/team-roles/{team_role_id}/root-dir",
            headers={"X-Owner-User-Id": "700"},
            json={"root_dir": "  "},
        )
        for response in (patch_422, reset_422, delete_422, working_422, root_422):
            self.assertEqual(response.status_code, 422)
            self.assertIn("error", response.json())

    def test_status_409_mapping_with_unified_error_envelope(self) -> None:
        client = self._client()
        _, _, team_role_id = self._team_and_role(client)
        conflict = Result.fail(
            ErrorCode.CONFLICT_ALREADY_EXISTS,
            "Conflict",
            details={"entity": "team_role", "cause": "state_conflict"},
            http_status=409,
        )
        with patch("app.interfaces.api.routers.read_only_v1.patch_team_role_result", return_value=conflict):
            response = client.patch(
                f"/api/v1/team-roles/{team_role_id}",
                headers={"X-Owner-User-Id": "700"},
                json={"enabled": True},
            )
        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "conflict.already_exists")
        self.assertIn("message", payload["error"])

    def test_write_endpoints_non_runner_reject_with_runtime_non_runner_code(self) -> None:
        client = self._client(dispatch_mode="single-runner", dispatch_is_runner=False)
        _, _, team_role_id = self._team_and_role(client)
        checks = [
            ("patch", f"/api/v1/team-roles/{team_role_id}", {"enabled": False}, {}),
            (
                "post",
                f"/api/v1/team-roles/{team_role_id}/reset-session",
                {"telegram_user_id": 700},
                {"Idempotency-Key": "idem-non-runner"},
            ),
            (
                "delete",
                f"/api/v1/team-roles/{team_role_id}",
                {"telegram_user_id": 700},
                {"Idempotency-Key": "idem-non-runner"},
            ),
            ("put", f"/api/v1/team-roles/{team_role_id}/skills/fs.list_dir", {"enabled": True}, {}),
            ("put", f"/api/v1/team-roles/{team_role_id}/working-dir", {"working_dir": "/tmp/work"}, {}),
            ("put", f"/api/v1/team-roles/{team_role_id}/root-dir", {"root_dir": "/tmp/root"}, {}),
            ("put", f"/api/v1/team-roles/{team_role_id}/prepost/echo", {"enabled": True}, {}),
        ]
        for method, path, payload, extra_headers in checks:
            headers = {"X-Owner-User-Id": "700", **extra_headers}
            response = client.request(method.upper(), path, headers=headers, json=payload)
            self.assertEqual(response.status_code, 409)
            body = response.json()
            self.assertEqual(body["error"]["code"], "runtime_non_runner_reject")
            self.assertEqual(body["error"]["details"].get("cause"), "non_runner_instance")

    def test_runtime_dispatch_health_endpoint_returns_operator_payload(self) -> None:
        client = self._client(dispatch_mode="single-runner", dispatch_is_runner=False)
        response = client.get("/api/v1/runtime/dispatch-health", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["mode"], "single-runner")
        self.assertEqual(body["is_runner"], False)
        self.assertEqual(body["queue_backend"], "in-memory")
        self.assertEqual(body["started_at"], "2026-04-05T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
