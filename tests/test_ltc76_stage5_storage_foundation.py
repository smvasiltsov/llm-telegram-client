from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class LTC76Stage5StorageFoundationTests(unittest.TestCase):
    def _bootstrap(self) -> tuple[Storage, int, int]:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        storage = Storage(Path(td.name) / "ltc76.sqlite3")
        with storage.transaction(immediate=True):
            group = storage.upsert_group(-9760, "stage5")
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

    def test_create_read_transition_and_idempotency(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            q = storage.create_question(
                question_id="q-001",
                thread_id="t-001",
                team_id=team_id,
                created_by_user_id=100,
                target_team_role_id=team_role_id,
                text="hello",
                status="accepted",
                origin_type="user",
            )
            idem = storage.upsert_qa_idempotency(
                scope="qa.create_question",
                idempotency_key="idem-001",
                payload_hash="hash-001",
                question_id=q.question_id,
            )
            answer = storage.create_answer(
                answer_id="a-001",
                question_id=q.question_id,
                thread_id=q.thread_id,
                team_id=q.team_id,
                team_role_id=team_role_id,
                role_name="dev",
                text="world",
            )
            q_after = storage.transition_question_status(
                question_id=q.question_id,
                status="answered",
                answered_at="2026-04-05T00:00:00+00:00",
            )
        self.assertEqual(idem.question_id, "q-001")
        self.assertEqual(answer.question_id, "q-001")
        self.assertIsNotNone(q_after)
        self.assertEqual(q_after.status if q_after else None, "answered")
        loaded = storage.get_question("q-001")
        self.assertEqual(loaded.status if loaded else None, "answered")

    def test_lineage_parent_answer_constraint(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            with self.assertRaisesRegex(ValueError, "parent_answer_id not found"):
                storage.create_question(
                    question_id="q-err",
                    thread_id="t-001",
                    team_id=team_id,
                    created_by_user_id=100,
                    target_team_role_id=team_role_id,
                    text="hello",
                    parent_answer_id="a-missing",
                )

    def test_journal_cursor_pagination(self) -> None:
        storage, team_id, _ = self._bootstrap()
        with storage.transaction(immediate=True):
            for i in range(1, 4):
                storage.create_question(
                    question_id=f"q-{i:03d}",
                    thread_id="t-001",
                    team_id=team_id,
                    created_by_user_id=100,
                    text=f"q{i}",
                )
        page1, c1 = storage.list_qa_journal(team_id=team_id, limit=2)
        page2, c2 = storage.list_qa_journal(team_id=team_id, limit=2, cursor=c1)
        self.assertEqual(len(page1), 2)
        self.assertEqual(len(page2), 1)
        self.assertIsNotNone(c1)
        self.assertIsNone(c2)
        ids = [item.question_id for item in page1 + page2]
        self.assertEqual(len(ids), len(set(ids)))

    def test_thread_answers_cursor(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            q = storage.create_question(
                question_id="q-thread",
                thread_id="t-xyz",
                team_id=team_id,
                created_by_user_id=100,
                target_team_role_id=team_role_id,
                text="hello",
            )
            for i in range(1, 4):
                storage.create_answer(
                    answer_id=f"a-{i:03d}",
                    question_id=q.question_id,
                    thread_id=q.thread_id,
                    team_id=q.team_id,
                    team_role_id=team_role_id,
                    role_name="dev",
                    text=f"a{i}",
                )
        page1, c1 = storage.list_thread_answers(thread_id="t-xyz", limit=2)
        page2, c2 = storage.list_thread_answers(thread_id="t-xyz", limit=2, cursor=c1)
        self.assertEqual(len(page1), 2)
        self.assertEqual(len(page2), 1)
        self.assertIsNotNone(c1)
        self.assertIsNone(c2)

    def test_orchestrator_feed_cursor(self) -> None:
        storage, team_id, team_role_id = self._bootstrap()
        with storage.transaction(immediate=True):
            for i in range(1, 4):
                q = storage.create_question(
                    question_id=f"q-feed-{i:03d}",
                    thread_id="t-feed",
                    team_id=team_id,
                    created_by_user_id=100,
                    target_team_role_id=team_role_id,
                    text=f"q{i}",
                )
                a = storage.create_answer(
                    answer_id=f"a-feed-{i:03d}",
                    question_id=q.question_id,
                    thread_id=q.thread_id,
                    team_id=q.team_id,
                    team_role_id=team_role_id,
                    role_name="dev",
                    text=f"a{i}",
                )
                storage.append_orchestrator_feed_item(
                    team_id=team_id,
                    thread_id=q.thread_id,
                    question_id=q.question_id,
                    answer_id=a.answer_id,
                )
        page1, c1 = storage.list_orchestrator_feed(team_id=team_id, limit=2)
        page2, c2 = storage.list_orchestrator_feed(team_id=team_id, limit=2, cursor=c1)
        self.assertEqual(len(page1), 2)
        self.assertEqual(len(page2), 1)
        self.assertIsNotNone(c1)
        self.assertIsNone(c2)


if __name__ == "__main__":
    unittest.main()
