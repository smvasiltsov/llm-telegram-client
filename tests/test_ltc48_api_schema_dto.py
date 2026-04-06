from __future__ import annotations

import unittest

from app.application.contracts.result import Result
from app.models import Role, RoleCatalogError, RoleCatalogItem, TeamRole, TeamRoleRuntimeStatus, TeamSessionView, UserRoleSession

_IMPORT_ERROR: Exception | None = None
try:
    from app.interfaces.api.schemas import (
        DeleteRequestDTO,
        ListRequestDTO,
        OperationResultDTO,
        RoleCatalogErrorDTO,
        RoleCatalogItemDTO,
        ResetRequestDTO,
        TeamSessionDTO,
        UpdateRequestDTO,
        delete_request_to_params,
        list_request_to_params,
        operation_result_to_dto,
        role_catalog_error_to_dto,
        role_catalog_item_to_dto,
        reset_request_to_params,
        role_to_dto,
        team_role_runtime_status_to_dto,
        team_role_to_dto,
        team_session_to_dto,
        update_request_to_patch,
        user_role_session_to_dto,
    )
except Exception as exc:  # pragma: no cover - environment-dependent dependency gap
    _IMPORT_ERROR = exc


class LTC48ApiSchemaDtoTests(unittest.TestCase):
    def setUp(self) -> None:
        if _IMPORT_ERROR is not None:
            self.skipTest(f"pydantic schemas are unavailable: {_IMPORT_ERROR}")

    def test_role_to_dto_from_domain_dataclass(self) -> None:
        role = Role(
            role_id=7,
            role_name="dev",
            description="Developer role",
            base_system_prompt="prompt",
            extra_instruction="extra",
            llm_model="gpt",
            is_active=True,
            mention_name="developer",
        )
        dto = role_to_dto(role)
        self.assertEqual(dto.role_id, 7)
        self.assertEqual(dto.role_name, "dev")
        self.assertEqual(dto.mention_name, "developer")

    def test_operation_requests_to_params(self) -> None:
        list_params = list_request_to_params(ListRequestDTO(team_id=10))
        self.assertEqual(list_params, {"team_id": 10, "active_only": True})

        update_patch = update_request_to_patch(
            UpdateRequestDTO(
                group_id=100,
                role_id=2,
                mode="orchestrator",
                system_prompt_override="new",
            )
        )
        self.assertEqual(
            update_patch,
            {
                "group_id": 100,
                "role_id": 2,
                "mode": "orchestrator",
                "system_prompt_override": "new",
            },
        )

        self.assertEqual(
            reset_request_to_params(ResetRequestDTO(group_id=-1, role_id=2, user_id=3)),
            {"group_id": -1, "role_id": 2, "user_id": 3},
        )
        self.assertEqual(
            delete_request_to_params(DeleteRequestDTO(group_id=-1, role_id=2, user_id=3)),
            {"group_id": -1, "role_id": 2, "user_id": 3},
        )

    def test_operation_result_to_dto_for_success_and_error(self) -> None:
        team_role = TeamRole(
            team_id=1,
            role_id=2,
            team_role_id=3,
            system_prompt_override=None,
            extra_instruction_override=None,
            display_name="Dev",
            model_override="gpt",
            user_prompt_suffix=None,
            user_reply_prefix=None,
            enabled=True,
            mode="normal",
            is_active=True,
        )
        session = UserRoleSession(
            telegram_user_id=10,
            group_id=-1,
            role_id=2,
            session_id="s1",
            created_at="2026-01-01T00:00:00Z",
            last_used_at="2026-01-01T00:00:00Z",
            team_id=1,
            team_role_id=3,
        )
        status = TeamRoleRuntimeStatus(
            team_role_id=3,
            status="busy",
            status_version=4,
            busy_request_id="req-1",
            busy_owner_user_id=10,
            busy_origin="group",
            preview_text=None,
            preview_source=None,
            busy_since="2026-01-01T00:00:00Z",
            lease_expires_at=None,
            last_heartbeat_at=None,
            free_release_requested_at=None,
            free_release_delay_until=None,
            free_release_reason_pending=None,
            last_release_reason=None,
            updated_at="2026-01-01T00:00:01Z",
        )

        team_role_result = operation_result_to_dto(Result.ok(team_role))
        session_result = operation_result_to_dto(Result.ok(session))
        status_result = operation_result_to_dto(Result.ok(status))
        error_result = operation_result_to_dto(Result.fail("validation.invalid_input", "bad input"))

        self.assertTrue(team_role_result.ok)
        self.assertEqual(team_role_result.team_role.role_id, 2)
        self.assertTrue(session_result.ok)
        self.assertEqual(session_result.session.session_id, "s1")
        self.assertTrue(status_result.ok)
        self.assertEqual(status_result.runtime_status.status, "busy")
        self.assertFalse(error_result.ok)
        self.assertEqual(error_result.message, "bad input")

    def test_direct_entity_dto_converters(self) -> None:
        team_role = TeamRole(
            team_id=1,
            role_id=2,
            team_role_id=3,
            system_prompt_override=None,
            extra_instruction_override=None,
            display_name=None,
            model_override=None,
            user_prompt_suffix=None,
            user_reply_prefix=None,
            enabled=False,
            mode="orchestrator",
            is_active=True,
        )
        status = TeamRoleRuntimeStatus(
            team_role_id=3,
            status="free",
            status_version=10,
            busy_request_id=None,
            busy_owner_user_id=None,
            busy_origin=None,
            preview_text=None,
            preview_source=None,
            busy_since=None,
            lease_expires_at=None,
            last_heartbeat_at=None,
            free_release_requested_at=None,
            free_release_delay_until=None,
            free_release_reason_pending=None,
            last_release_reason="manual",
            updated_at="2026-01-01T00:00:01Z",
        )
        session = UserRoleSession(
            telegram_user_id=1,
            group_id=-100,
            role_id=2,
            session_id="abc",
            created_at="2026-01-01T00:00:00Z",
            last_used_at="2026-01-01T00:00:10Z",
            team_id=1,
            team_role_id=3,
        )
        self.assertEqual(team_role_to_dto(team_role).mode, "orchestrator")
        self.assertEqual(team_role_runtime_status_to_dto(status).status, "free")
        self.assertEqual(user_role_session_to_dto(session).team_role_id, 3)

        empty_result = OperationResultDTO(ok=True)
        self.assertTrue(empty_result.ok)

    def test_catalog_and_session_dto_converters(self) -> None:
        catalog_item = RoleCatalogItem(
            role_name="dev",
            is_active=True,
            llm_model="gpt",
            is_orchestrator=True,
            has_errors=False,
            source="/tmp/roles/dev.json",
        )
        catalog_error = RoleCatalogError(
            role_name="broken",
            file="/tmp/roles/broken.json",
            code="invalid_json",
            message="bad json",
            details={"source": "catalog"},
        )
        session = TeamSessionView(
            telegram_user_id=42,
            team_role_id=7,
            role_name="dev",
            session_id="s-1",
            updated_at="2026-01-01T00:00:00Z",
        )
        self.assertIsInstance(role_catalog_item_to_dto(catalog_item), RoleCatalogItemDTO)
        self.assertIsInstance(role_catalog_error_to_dto(catalog_error), RoleCatalogErrorDTO)
        self.assertIsInstance(team_session_to_dto(session), TeamSessionDTO)


if __name__ == "__main__":
    unittest.main()
