from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.application.use_cases.recovery_reset import reset_recovery_queues_result
from app.storage import Storage


class RecoveryResetUseCaseTests(unittest.TestCase):
    def _prepare_team_role(self, storage: Storage, chat_id: int, role_name: str) -> tuple[int, int]:
        with storage.transaction(immediate=True):
            group = storage.upsert_group(chat_id, f"group-{chat_id}")
            role = storage.upsert_role(
                role_name=role_name,
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.ensure_group_role(group.group_id, role.role_id)
            team_id = int(group.team_id or 0)
            team_role_id = int(storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True) or 0)
            if team_role_id <= 0:
                raise AssertionError("team_role_id missing")
        return team_id, team_role_id

    def _seed_failed_runtime_state(self, storage: Storage, *, team_id: int, team_role_id: int, suffix: str) -> str:
        with storage.transaction(immediate=True):
            q = storage.create_question(
                question_id=f"q-{suffix}",
                thread_id=f"t-{suffix}",
                team_id=team_id,
                created_by_user_id=700,
                target_team_role_id=team_role_id,
                text=f"text-{suffix}",
                status="accepted",
            )
            storage.transition_question_status(question_id=q.question_id, status="queued")
            started = storage.start_question_dispatch_attempt(question_id=q.question_id, lease_ttl_sec=120, max_attempts=3)
            self.assertIsNotNone(started)
            ev = storage.create_thread_event(
                team_id=team_id,
                thread_id=f"t-{suffix}",
                event_type="thread.message.created",
                author_type="user",
                direction="question",
                origin_interface="telegram",
                source_ref_type="question",
                source_ref_id=q.question_id,
                question_id=q.question_id,
            )
            pending = storage.enqueue_event_delivery(
                event_id=ev.event_id,
                interface_type="mirror",
                target_id=f"pending-{suffix}",
            )
            retry = storage.enqueue_event_delivery(
                event_id=ev.event_id,
                interface_type="mirror",
                target_id=f"retry-{suffix}",
            )
            progress = storage.enqueue_event_delivery(
                event_id=ev.event_id,
                interface_type="mirror",
                target_id=f"progress-{suffix}",
            )
            _ = storage.mark_event_delivery_retry(
                int(retry.delivery_id),
                error_code="tmp",
                error_message="tmp",
                retry_delay_sec=0,
            )
            claimed = storage.claim_pending_event_deliveries(limit=10, lease_owner=f"worker-{suffix}", lease_ttl_sec=120)
            claimed_ids = {int(item.delivery_id) for item in claimed}
            self.assertIn(int(progress.delivery_id), claimed_ids)
            self.assertIn(int(pending.delivery_id), claimed_ids)
        acquired, _, _ = storage.try_acquire_team_role_busy(
            team_role_id=team_role_id,
            busy_request_id=f"busy-{suffix}",
            busy_owner_user_id=700,
            busy_origin="qa",
            preview_text="busy",
            preview_source="user",
            busy_since="2026-04-15T00:00:00+00:00",
            lease_expires_at="2026-04-15T00:05:00+00:00",
        )
        self.assertTrue(acquired)
        return f"q-{suffix}"

    def test_dry_run_does_not_apply_changes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "recovery.sqlite3")
            team_id, team_role_id = self._prepare_team_role(storage, -9901, "dev_recovery_dry")
            question_id = self._seed_failed_runtime_state(storage, team_id=team_id, team_role_id=team_role_id, suffix="dry")

            result = reset_recovery_queues_result(
                storage,
                scope_mode="global",
                team_id=None,
                dry_run=True,
            )
            self.assertTrue(result.is_ok)
            self.assertIsNotNone(result.value)
            self.assertFalse(result.value.applied if result.value else True)
            self.assertEqual(result.value.before, result.value.after)

            question = storage.get_question(question_id)
            self.assertEqual((question.status if question else None), "in_progress")

    def test_apply_team_scope_resets_only_selected_team(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "recovery.sqlite3")
            team_a, team_role_a = self._prepare_team_role(storage, -9902, "dev_recovery_a")
            team_b, team_role_b = self._prepare_team_role(storage, -9903, "dev_recovery_b")
            q_a = self._seed_failed_runtime_state(storage, team_id=team_a, team_role_id=team_role_a, suffix="a")
            q_b = self._seed_failed_runtime_state(storage, team_id=team_b, team_role_id=team_role_b, suffix="b")

            result = reset_recovery_queues_result(
                storage,
                scope_mode="team",
                team_id=team_a,
                dry_run=False,
            )
            self.assertTrue(result.is_ok)
            self.assertIsNotNone(result.value)
            self.assertTrue(result.value.applied if result.value else False)
            self.assertEqual((result.value.after.questions_in_progress if result.value else -1), 0)

            question_a = storage.get_question(q_a)
            question_b = storage.get_question(q_b)
            self.assertEqual((question_a.status if question_a else None), "accepted")
            self.assertEqual((question_b.status if question_b else None), "in_progress")

            status_a = storage.get_team_role_runtime_status(team_role_a)
            status_b = storage.get_team_role_runtime_status(team_role_b)
            self.assertEqual((status_a.status if status_a else None), "free")
            self.assertEqual((status_b.status if status_b else None), "busy")
