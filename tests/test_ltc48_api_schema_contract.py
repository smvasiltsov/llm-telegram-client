from __future__ import annotations

import unittest

_IMPORT_ERROR: Exception | None = None
try:
    from app.interfaces.api.schemas import (
        OperationResultDTO,
        RoleDTO,
        TeamRoleRuntimeStatusDTO,
        UpdateRequestDTO,
    )
except Exception as exc:  # pragma: no cover - environment-dependent dependency gap
    _IMPORT_ERROR = exc


class LTC48ApiSchemaContractTests(unittest.TestCase):
    def setUp(self) -> None:
        if _IMPORT_ERROR is not None:
            self.skipTest(f"pydantic schemas are unavailable: {_IMPORT_ERROR}")

    def test_role_dto_json_shape_contract(self) -> None:
        dto = RoleDTO(
            role_id=1,
            role_name="dev",
            description="Developer",
            base_system_prompt="sys",
            extra_instruction="extra",
            llm_model=None,
            is_active=True,
            mention_name=None,
        )
        self.assertEqual(
            dto.model_dump(mode="json"),
            {
                "role_id": 1,
                "role_name": "dev",
                "description": "Developer",
                "base_system_prompt": "sys",
                "extra_instruction": "extra",
                "llm_model": None,
                "is_active": True,
                "mention_name": None,
            },
        )

    def test_team_role_runtime_status_json_shape_contract(self) -> None:
        dto = TeamRoleRuntimeStatusDTO(
            team_role_id=10,
            status="free",
            status_version=7,
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
            last_release_reason="timeout",
            updated_at="2026-01-01T00:00:01Z",
        )
        self.assertEqual(
            dto.model_dump(mode="json"),
            {
                "team_role_id": 10,
                "status": "free",
                "status_version": 7,
                "busy_request_id": None,
                "busy_owner_user_id": None,
                "busy_origin": None,
                "preview_text": None,
                "preview_source": None,
                "busy_since": None,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "free_release_requested_at": None,
                "free_release_delay_until": None,
                "free_release_reason_pending": None,
                "last_release_reason": "timeout",
                "updated_at": "2026-01-01T00:00:01Z",
            },
        )

    def test_update_request_patch_shape_contract(self) -> None:
        dto = UpdateRequestDTO(
            group_id=-100,
            role_id=2,
            enabled=True,
            mode="normal",
            model_override="gpt",
            system_prompt_override=None,
            extra_instruction_override=None,
            user_prompt_suffix=None,
            user_reply_prefix=None,
        )
        self.assertEqual(
            dto.model_dump(exclude_none=True, mode="json"),
            {
                "group_id": -100,
                "role_id": 2,
                "enabled": True,
                "mode": "normal",
                "model_override": "gpt",
            },
        )

    def test_operation_result_shape_contract(self) -> None:
        dto = OperationResultDTO(ok=False, message="failed")
        self.assertEqual(
            dto.model_dump(mode="json"),
            {
                "ok": False,
                "message": "failed",
                "team_role": None,
                "session": None,
                "runtime_status": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
