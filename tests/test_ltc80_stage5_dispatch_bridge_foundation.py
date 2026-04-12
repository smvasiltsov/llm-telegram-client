from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.application.use_cases.qa_dispatch_bridge import (
    claim_questions_for_dispatch_result,
    persist_question_terminal_outcome_result,
    start_question_dispatch_attempt_result,
    sweep_expired_question_dispatch_leases_result,
)
from app.storage import Storage


class LTC80Stage5DispatchBridgeFoundationTests(unittest.TestCase):
    def _bootstrap(self) -> tuple[Storage, int, int]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        storage = Storage(Path(td.name) / "ltc80.sqlite3")
        with storage.transaction(immediate=True):
            group = storage.upsert_group(-9800, "bridge")
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

    def test_claim_and_start_transitions(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            storage.create_question(
                question_id="q-bridge-1",
                thread_id="t-bridge-1",
                team_id=team_id,
                created_by_user_id=100,
                target_team_role_id=team_role_id,
                text="hello",
                status="accepted",
            )
        claimed = claim_questions_for_dispatch_result(storage, limit=10, max_attempts=3)
        self.assertTrue(claimed.is_ok)
        self.assertEqual([q.question_id for q in (claimed.value or [])], ["q-bridge-1"])
        self.assertEqual((storage.get_question("q-bridge-1").status if storage.get_question("q-bridge-1") else None), "queued")

        started = start_question_dispatch_attempt_result(storage, question_id="q-bridge-1", lease_ttl_sec=120, max_attempts=3)
        self.assertTrue(started.is_ok)
        self.assertEqual((started.value.status if started.value else None), "in_progress")

    def test_terminal_persist_is_atomic_for_answer_and_feed(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            storage.create_question(
                question_id="q-bridge-2",
                thread_id="t-bridge-2",
                team_id=team_id,
                created_by_user_id=100,
                target_team_role_id=team_role_id,
                text="hello",
                status="queued",
            )
            storage.start_question_dispatch_attempt(question_id="q-bridge-2", lease_ttl_sec=120, max_attempts=3)

        outcome = persist_question_terminal_outcome_result(
            storage,
            question_id="q-bridge-2",
            status="answered",
            answer_id="a-bridge-2",
            answer_text="world",
            answer_team_role_id=team_role_id,
            answer_role_name="dev",
            append_orchestrator_feed=True,
        )
        self.assertTrue(outcome.is_ok)
        self.assertEqual((outcome.value.question.status if outcome.value else None), "answered")
        self.assertIsNotNone(outcome.value.answer if outcome.value else None)
        self.assertIsNotNone(outcome.value.orchestrator_feed_item if outcome.value else None)

    def test_lease_sweep_requeues_then_times_out_on_attempt_cap(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            storage.create_question(
                question_id="q-bridge-3",
                thread_id="t-bridge-3",
                team_id=team_id,
                created_by_user_id=100,
                target_team_role_id=team_role_id,
                text="hello",
                status="accepted",
            )
            storage.claim_questions_for_dispatch(limit=1, max_attempts=3, now="2026-04-06T00:00:00+00:00")
            storage.start_question_dispatch_attempt(
                question_id="q-bridge-3",
                lease_ttl_sec=120,
                max_attempts=3,
                now="2026-04-06T00:00:00+00:00",
            )

        sweep1 = sweep_expired_question_dispatch_leases_result(
            storage,
            max_attempts=3,
            attempt_ttl_sec=120,
            now="2026-04-06T00:01:00+00:00",
        )
        self.assertTrue(sweep1.is_ok)
        self.assertEqual(len(sweep1.value.requeued if sweep1.value else []), 0)

        # Force two more attempts and expire both to hit max attempt cap.
        with storage.transaction(immediate=True):
            storage.sweep_expired_question_dispatch_leases(
                now="2026-04-06T00:02:01+00:00",
                max_attempts=3,
                attempt_ttl_sec=120,
            )
            storage.start_question_dispatch_attempt(
                question_id="q-bridge-3",
                lease_ttl_sec=120,
                max_attempts=3,
                now="2026-04-06T00:02:01+00:00",
            )
            storage.sweep_expired_question_dispatch_leases(
                now="2026-04-06T00:04:02+00:00",
                max_attempts=3,
                attempt_ttl_sec=120,
            )
            storage.start_question_dispatch_attempt(
                question_id="q-bridge-3",
                lease_ttl_sec=120,
                max_attempts=3,
                now="2026-04-06T00:04:02+00:00",
            )
            requeued, timed_out = storage.sweep_expired_question_dispatch_leases(
                now="2026-04-06T00:06:03+00:00",
                max_attempts=3,
                attempt_ttl_sec=120,
            )
        self.assertEqual(len(requeued), 0)
        self.assertEqual(len(timed_out), 1)
        final = storage.get_question("q-bridge-3")
        self.assertEqual((final.status if final else None), "timeout")
        self.assertEqual((final.error_code if final else None), "runtime_dispatch_timeout")

    def test_heartbeat_does_not_revive_expired_lease(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            storage.create_question(
                question_id="q-bridge-hb-expired",
                thread_id="t-bridge-hb-expired",
                team_id=team_id,
                created_by_user_id=100,
                target_team_role_id=team_role_id,
                text="hello",
                status="accepted",
            )
            storage.claim_questions_for_dispatch(limit=1, max_attempts=3, now="2026-04-06T00:00:00+00:00")
            storage.start_question_dispatch_attempt(
                question_id="q-bridge-hb-expired",
                lease_ttl_sec=10,
                max_attempts=3,
                now="2026-04-06T00:00:00+00:00",
            )
        with storage.transaction(immediate=True):
            alive = storage.heartbeat_question_dispatch_attempt(
                question_id="q-bridge-hb-expired",
                lease_ttl_sec=10,
                now="2026-04-06T00:00:20+00:00",
            )
        self.assertFalse(alive)

        sweep = sweep_expired_question_dispatch_leases_result(
            storage,
            max_attempts=3,
            attempt_ttl_sec=10,
            now="2026-04-06T00:00:20+00:00",
        )
        self.assertTrue(sweep.is_ok)
        item = storage.get_question("q-bridge-hb-expired")
        self.assertEqual((item.status if item else None), "queued")


if __name__ == "__main__":
    unittest.main()
