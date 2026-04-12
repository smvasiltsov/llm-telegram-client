from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.llm_providers import ProviderConfig, ProviderModel, ProviderUserField
from app.application.use_cases.qa_api import (
    QaCreateQuestionRequest,
    create_question_result,
    get_question_status_result,
    get_thread_result,
    list_orchestrator_feed_result,
    list_qa_journal_result,
    map_runtime_pending_to_qa_contract,
    resolve_answer_by_question_result,
    transition_question_status_result,
)
from app.storage import Storage


class LTC77Stage5QaUseCasesTests(unittest.TestCase):
    def _bootstrap(self) -> tuple[Storage, int, int]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        storage = Storage(Path(td.name) / "ltc77.sqlite3")
        with storage.transaction(immediate=True):
            group = storage.upsert_group(-9770, "qa")
            role = storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
        team_id = int(group.team_id or 0)
        team_role_id = storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True)
        if team_role_id is None:
            raise AssertionError("team_role_id missing")
        return storage, team_id, int(team_role_id)

    def test_create_question_idempotency_and_mismatch(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        req = QaCreateQuestionRequest(
            team_id=team_id,
            created_by_user_id=101,
            text="hello",
            team_role_id=team_role_id,
            thread_id="thread-1",
            question_id="question-1",
        )
        first = create_question_result(storage, request=req, idempotency_key="idem-1")
        second = create_question_result(storage, request=req, idempotency_key="idem-1")
        mismatch = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="different",
                team_role_id=team_role_id,
                thread_id="thread-1",
                question_id="question-1",
            ),
            idempotency_key="idem-1",
        )
        self.assertTrue(first.is_ok)
        self.assertTrue(second.is_ok)
        self.assertTrue(second.value.idempotent_replay if second.value else False)
        self.assertTrue(mismatch.is_error)
        self.assertEqual((mismatch.error.code if mismatch.error else None), "qa_idempotency_mismatch")

    def test_transition_status_machine_and_get_status(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        created = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="hello",
                team_role_id=team_role_id,
                thread_id="thread-2",
                question_id="question-2",
            ),
            idempotency_key="idem-2",
        )
        self.assertTrue(created.is_ok)
        queued = transition_question_status_result(storage, question_id="question-2", to_status="queued")
        running = transition_question_status_result(storage, question_id="question-2", to_status="in_progress")
        answered = transition_question_status_result(storage, question_id="question-2", to_status="answered")
        invalid = transition_question_status_result(storage, question_id="question-2", to_status="queued")
        current = get_question_status_result(storage, question_id="question-2")

        self.assertTrue(queued.is_ok)
        self.assertTrue(running.is_ok)
        self.assertTrue(answered.is_ok)
        self.assertTrue(invalid.is_error)
        self.assertEqual((invalid.error.code if invalid.error else None), "qa_lineage_invalid")
        self.assertTrue(current.is_ok)
        self.assertEqual((current.value.status if current.value else None), "answered")

    def test_resolve_answer_not_ready_and_timeout(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        created = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="hello",
                team_role_id=team_role_id,
                thread_id="thread-3",
                question_id="question-3",
            ),
            idempotency_key="idem-3",
        )
        self.assertTrue(created.is_ok)
        not_ready = resolve_answer_by_question_result(storage, question_id="question-3")
        self.assertTrue(not_ready.is_error)
        self.assertEqual((not_ready.error.code if not_ready.error else None), "qa_answer_not_ready")

        transition_question_status_result(storage, question_id="question-3", to_status="queued")
        transition_question_status_result(storage, question_id="question-3", to_status="in_progress")
        transition_question_status_result(
            storage,
            question_id="question-3",
            to_status="timeout",
            error_code="qa_timeout",
            error_message="Timed out",
        )
        timeout = resolve_answer_by_question_result(storage, question_id="question-3")
        self.assertTrue(timeout.is_error)
        self.assertEqual((timeout.error.code if timeout.error else None), "qa_timeout")

    def test_journal_thread_and_feed_use_cases(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            q1 = storage.create_question(
                question_id="q-j-1",
                thread_id="thread-j",
                team_id=team_id,
                created_by_user_id=100,
                target_team_role_id=team_role_id,
                text="q1",
            )
            a1 = storage.create_answer(
                answer_id="a-j-1",
                question_id=q1.question_id,
                thread_id=q1.thread_id,
                team_id=q1.team_id,
                team_role_id=team_role_id,
                role_name="dev",
                text="a1",
            )
            storage.append_orchestrator_feed_item(
                team_id=team_id,
                thread_id=q1.thread_id,
                question_id=q1.question_id,
                answer_id=a1.answer_id,
            )

        journal = list_qa_journal_result(storage, team_id=team_id, limit=10)
        thread = get_thread_result(storage, thread_id="thread-j", limit=10)
        feed = list_orchestrator_feed_result(storage, team_id=team_id, limit=10)
        self.assertTrue(journal.is_ok)
        self.assertTrue(thread.is_ok)
        self.assertTrue(feed.is_ok)
        self.assertEqual(len(journal.value.items if journal.value else []), 1)
        self.assertEqual(len(thread.value.questions.items if thread.value else []), 1)
        self.assertEqual(len(thread.value.answers.items if thread.value else []), 1)
        self.assertEqual(len(feed.value.items if feed.value else []), 1)

    def test_runtime_pending_mapping(self) -> None:
        s1, c1 = map_runtime_pending_to_qa_contract(
            runtime_status="busy",
            pending_exists=False,
            pending_replay_failed=False,
            timed_out=False,
        )
        s2, c2 = map_runtime_pending_to_qa_contract(
            runtime_status="free",
            pending_exists=True,
            pending_replay_failed=False,
            timed_out=False,
        )
        s3, c3 = map_runtime_pending_to_qa_contract(
            runtime_status="busy",
            pending_exists=True,
            pending_replay_failed=True,
            timed_out=False,
        )
        self.assertEqual((s1, c1), ("in_progress", None))
        self.assertEqual((s2, c2), ("queued", None))
        self.assertEqual((s3, c3), ("failed", "qa_timeout"))

    def test_create_question_tag_based_routing_when_team_role_absent(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        result = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="please handle @dev",
                thread_id="thread-tag-1",
                question_id="question-tag-1",
            ),
            idempotency_key="idem-tag-1",
        )
        self.assertTrue(result.is_ok)
        self.assertEqual((result.value.question.target_team_role_id if result.value else None), team_role_id)

    def test_create_question_explicit_team_role_has_priority_over_tags(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            role2 = storage.upsert_role(
                role_name="ops",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.bind_master_role_to_team(team_id, role2.role_id)
            ops_team_role_id = int(storage.resolve_team_role_id(team_id, role2.role_id, ensure_exists=True) or 0)
        result = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="tag says @dev but explicit should win",
                team_role_id=ops_team_role_id,
                thread_id="thread-tag-2",
                question_id="question-tag-2",
            ),
            idempotency_key="idem-tag-2",
        )
        self.assertTrue(result.is_ok)
        self.assertEqual((result.value.question.target_team_role_id if result.value else None), ops_team_role_id)
        self.assertNotEqual(ops_team_role_id, team_role_id)

    def test_create_question_missing_tag_returns_422(self) -> None:
        storage, team_id, _ = self._bootstrap()
        result = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="no tags here",
                thread_id="thread-tag-3",
                question_id="question-tag-3",
            ),
            idempotency_key="idem-tag-3",
        )
        self.assertTrue(result.is_error)
        self.assertEqual((result.error.code if result.error else None), "qa_orchestrator_not_configured")
        self.assertEqual((result.error.http_status if result.error else None), 422)

    def test_create_question_missing_tag_uses_single_active_orchestrator(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        identity = storage.resolve_team_role_identity(team_role_id)
        if identity is None:
            raise AssertionError("team_role identity missing")
        _, role_id = identity
        with storage.transaction(immediate=True):
            storage.set_team_role_mode(team_id, role_id, "orchestrator")
        result = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="no tag, route to orchestrator",
                thread_id="thread-tag-3a",
                question_id="question-tag-3a",
            ),
            idempotency_key="idem-tag-3a",
        )
        self.assertTrue(result.is_ok)
        self.assertEqual((result.value.question.target_team_role_id if result.value else None), team_role_id)

    def test_create_question_missing_tag_with_multiple_orchestrators_returns_422(self) -> None:
        storage, team_id, _ = self._bootstrap()
        with storage.transaction(immediate=True):
            role2 = storage.upsert_role(
                role_name="ops",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.bind_master_role_to_team(team_id, role2.role_id)
            # Simulate corrupted state with two active orchestrators to validate deterministic API mapping.
            storage._conn.execute(  # noqa: SLF001 - intentional white-box setup for ambiguity branch
                "UPDATE team_roles SET mode = 'orchestrator', enabled = 1, is_active = 1 WHERE team_id = ?",
                (team_id,),
            )
        result = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="no tag and ambiguous orchestrator",
                thread_id="thread-tag-3b",
                question_id="question-tag-3b",
            ),
            idempotency_key="idem-tag-3b",
        )
        self.assertTrue(result.is_error)
        self.assertEqual((result.error.code if result.error else None), "qa_orchestrator_ambiguous")
        self.assertEqual((result.error.http_status if result.error else None), 422)

    def test_create_question_multiple_tags_returns_422(self) -> None:
        storage, team_id, _ = self._bootstrap()
        with storage.transaction(immediate=True):
            role2 = storage.upsert_role(
                role_name="ops",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.bind_master_role_to_team(team_id, role2.role_id)
        result = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="@dev and @ops",
                thread_id="thread-tag-4",
                question_id="question-tag-4",
            ),
            idempotency_key="idem-tag-4",
        )
        self.assertTrue(result.is_error)
        self.assertEqual((result.error.code if result.error else None), "qa_lineage_invalid")
        self.assertEqual((result.error.http_status if result.error else None), 422)

    def test_create_question_team_role_team_mismatch_returns_422(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            other_group = storage.upsert_group(-9771, "qa2")
            other_team_id = int(other_group.team_id or 0)
            other_role = storage.upsert_role(
                role_name="ops2",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(other_group.group_id, other_role.role_id)
            other_team_role_id = int(storage.resolve_team_role_id(other_team_id, other_role.role_id, ensure_exists=True) or 0)
        self.assertNotEqual(team_role_id, other_team_role_id)
        result = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="explicit mismatched role",
                team_role_id=other_team_role_id,
                thread_id="thread-tag-5",
                question_id="question-tag-5",
            ),
            idempotency_key="idem-tag-5",
        )
        self.assertTrue(result.is_error)
        self.assertEqual((result.error.code if result.error else None), "qa_lineage_invalid")
        self.assertEqual((result.error.http_status if result.error else None), 422)

    def test_create_question_team_or_team_role_not_found_returns_404_qa_not_found(self) -> None:
        storage, _, _ = self._bootstrap()
        missing_team = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=999999,
                created_by_user_id=101,
                text="x",
                team_role_id=1,
                thread_id="thread-tag-6",
                question_id="question-tag-6",
            ),
            idempotency_key="idem-tag-6",
        )
        self.assertTrue(missing_team.is_error)
        self.assertEqual((missing_team.error.code if missing_team.error else None), "qa_not_found")
        self.assertEqual((missing_team.error.http_status if missing_team.error else None), 404)

        storage2, team_id2, _ = self._bootstrap()
        missing_team_role = create_question_result(
            storage2,
            request=QaCreateQuestionRequest(
                team_id=team_id2,
                created_by_user_id=101,
                text="x",
                team_role_id=999999,
                thread_id="thread-tag-7",
                question_id="question-tag-7",
            ),
            idempotency_key="idem-tag-7",
        )
        self.assertTrue(missing_team_role.is_error)
        self.assertEqual((missing_team_role.error.code if missing_team_role.error else None), "qa_not_found")
        self.assertEqual((missing_team_role.error.http_status if missing_team_role.error else None), 404)

    def test_create_question_requires_working_and_root_dirs_for_fs_skills(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            storage.upsert_role_skill_for_team_role(team_role_id, "fs.read_file", enabled=True, config={})
        result_missing = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="please handle @dev",
                team_role_id=team_role_id,
                thread_id="thread-fs-1",
                question_id="question-fs-1",
            ),
            idempotency_key="idem-fs-1",
        )
        self.assertTrue(result_missing.is_error)
        self.assertEqual((result_missing.error.code if result_missing.error else None), "validation.invalid_input")
        self.assertEqual((result_missing.error.http_status if result_missing.error else None), 422)
        self.assertEqual(
            (result_missing.error.details if result_missing.error else {}).get("missing_fields"),
            ["root_dir"],
        )

        with storage.transaction(immediate=True):
            storage.set_team_role_root_dir_by_id(team_role_id, "/abs/root")
        result_missing_root = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="please handle @dev",
                team_role_id=team_role_id,
                thread_id="thread-fs-2",
                question_id="question-fs-2",
            ),
            idempotency_key="idem-fs-2",
        )
        self.assertTrue(result_missing_root.is_ok)

        with storage.transaction(immediate=True):
            storage.set_team_role_working_dir_by_id(team_role_id, "/abs/work")
        result_ok = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="please handle @dev",
                team_role_id=team_role_id,
                thread_id="thread-fs-3",
                question_id="question-fs-3",
            ),
            idempotency_key="idem-fs-3",
        )
        self.assertTrue(result_ok.is_ok)

    def test_create_question_requires_working_dir_from_provider_user_fields(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            identity = storage.resolve_team_role_identity(team_role_id)
            if identity is None:
                raise AssertionError("team_role identity missing")
            _, role_id = identity
            storage.set_team_role_model(team_id, role_id, "codex-api:gpt-5")

        provider_model = ProviderModel(provider_id="codex-api", model_id="gpt-5", label="GPT-5")
        provider_registry = {
            "codex-api": ProviderConfig(
                provider_id="codex-api",
                label="Codex",
                base_url="http://localhost",
                tls_ca_cert_path=None,
                adapter="generic",
                capabilities={},
                auth_mode="none",
                endpoints={},
                models=[provider_model],
                history_enabled=False,
                history_limit=None,
                user_fields={
                    "working_dir": ProviderUserField(
                        key="working_dir",
                        prompt="Enter working_dir",
                        scope="role",
                    )
                },
            )
        }
        result_missing = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="please handle @dev",
                team_role_id=team_role_id,
                thread_id="thread-wd-1",
                question_id="question-wd-1",
            ),
            idempotency_key="idem-wd-1",
            provider_registry=provider_registry,
            provider_models=[provider_model],
            provider_model_map={provider_model.full_id: provider_model},
            default_provider_id="codex-api",
        )
        self.assertTrue(result_missing.is_error)
        self.assertEqual(
            (result_missing.error.details if result_missing.error else {}).get("missing_fields"),
            ["working_dir"],
        )

        with storage.transaction(immediate=True):
            storage.set_team_role_working_dir_by_id(team_role_id, "/abs/work")
        result_ok = create_question_result(
            storage,
            request=QaCreateQuestionRequest(
                team_id=team_id,
                created_by_user_id=101,
                text="please handle @dev",
                team_role_id=team_role_id,
                thread_id="thread-wd-2",
                question_id="question-wd-2",
            ),
            idempotency_key="idem-wd-2",
            provider_registry=provider_registry,
            provider_models=[provider_model],
            provider_model_map={provider_model.full_id: provider_model},
            default_provider_id="codex-api",
        )
        self.assertTrue(result_ok.is_ok)


if __name__ == "__main__":
    unittest.main()
