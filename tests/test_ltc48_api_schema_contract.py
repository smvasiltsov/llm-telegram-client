from __future__ import annotations

import unittest

_IMPORT_ERROR: Exception | None = None
ValidationError = Exception
try:
    from pydantic import ValidationError as _ValidationError
    from app.interfaces.api.schemas import (
        ApiPagedResponse,
        OperationResultDTO,
        QaCreateQuestionRequestDTO,
        RoleDTO,
        TeamRoleRuntimeStatusDTO,
        UpdateRequestDTO,
    )
    ValidationError = _ValidationError
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
                "team_role_id": None,
                "role_name": "dev",
                "description": "Developer",
                "base_system_prompt": "sys",
                "extra_instruction": "extra",
                "llm_model": None,
                "is_active": True,
                "is_orchestrator": False,
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

    def test_paged_response_shape_contract(self) -> None:
        dto = ApiPagedResponse(items=[{"team_id": 1}], meta={"total": 1, "limit": 50, "offset": 0, "returned": 1})
        self.assertEqual(
            dto.model_dump(mode="json"),
            {
                "items": [{"team_id": 1}],
                "meta": {"total": 1, "limit": 50, "offset": 0, "returned": 1},
            },
        )

    def test_strict_contract_rejects_unknown_fields(self) -> None:
        with self.assertRaises(ValidationError):
            RoleDTO(
                role_id=1,
                role_name="dev",
                description="Developer",
                base_system_prompt="sys",
                extra_instruction="extra",
                llm_model=None,
                is_active=True,
                mention_name=None,
                unexpected_field="boom",
            )

    def test_qa_create_question_contract_requires_team_id_and_uses_team_role_id(self) -> None:
        dto = QaCreateQuestionRequestDTO(
            team_id=1,
            text="hello",
            team_role_id=7,
        )
        self.assertEqual(
            dto.model_dump(mode="json"),
            {
                "team_id": 1,
                "text": "hello",
                "team_role_id": 7,
                "origin_type": "user",
                "source_question_id": None,
                "parent_answer_id": None,
                "thread_id": None,
                "question_id": None,
            },
        )
        with self.assertRaises(ValidationError):
            QaCreateQuestionRequestDTO(
                text="hello",
            )
        with self.assertRaises(ValidationError):
            QaCreateQuestionRequestDTO(
                team_id=1,
                text="hello",
                target_team_role_id=7,
            )


if __name__ == "__main__":
    unittest.main()
