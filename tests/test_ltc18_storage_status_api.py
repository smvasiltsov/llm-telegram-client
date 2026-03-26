from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class LTC18StorageStatusApiTests(unittest.TestCase):
    def test_runtime_status_lifecycle_for_team_role(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "status.sqlite3")
            team_role_id = self._seed_team_role(storage, team_public_id="team-a", role_name="analyst")

            status = storage.ensure_team_role_runtime_status(team_role_id)
            self.assertEqual(status.status, "free")

            busy = storage.mark_team_role_runtime_busy(
                team_role_id,
                busy_request_id="req-1",
                busy_owner_user_id=101,
                busy_origin="group",
                preview_text="User asked to summarize sprint risks",
                preview_source="user",
                busy_since="2026-03-26T10:00:00+00:00",
                lease_expires_at="2026-03-26T10:10:00+00:00",
            )
            self.assertEqual(busy.status, "busy")
            self.assertEqual(busy.busy_request_id, "req-1")
            self.assertIsNone(busy.free_release_requested_at)

            storage.update_team_role_runtime_preview(
                team_role_id,
                preview_text="skill step summary",
                preview_source="skill_engine",
            )
            touched = storage.get_team_role_runtime_status(team_role_id)
            self.assertIsNotNone(touched)
            self.assertEqual(touched.preview_source if touched else None, "skill_engine")

            free = storage.mark_team_role_runtime_free(team_role_id, release_reason="response_sent")
            self.assertEqual(free.status, "free")
            self.assertIsNone(free.busy_request_id)
            self.assertIsNone(free.preview_text)
            self.assertIsNone(free.free_release_requested_at)

    def test_delayed_release_request_and_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "delay.sqlite3")
            team_role_id = self._seed_team_role(storage, team_public_id="team-a", role_name="analyst")

            storage.mark_team_role_runtime_busy(
                team_role_id,
                busy_request_id="req-2",
                busy_owner_user_id=201,
                busy_origin="group",
                preview_text="Long task",
                preview_source="user",
                busy_since="2026-03-26T10:00:00+00:00",
                lease_expires_at="2026-03-26T10:10:00+00:00",
                now="2026-03-26T10:00:00+00:00",
            )

            requested = storage.mark_team_role_runtime_release_requested(
                team_role_id,
                release_reason="response_sent",
                requested_at="2026-03-26T10:01:00+00:00",
                delay_until="2026-03-26T10:01:10+00:00",
            )
            self.assertEqual(requested.status, "busy")
            self.assertEqual(requested.free_release_reason_pending, "response_sent")
            self.assertEqual(requested.free_release_delay_until, "2026-03-26T10:01:10+00:00")
            self.assertEqual(requested.preview_text, "Long task")

            due_early = storage.list_due_team_role_runtime_releases(now="2026-03-26T10:01:05+00:00")
            self.assertEqual(len(due_early), 0)
            due_ready = storage.list_due_team_role_runtime_releases(now="2026-03-26T10:01:10+00:00")
            self.assertEqual(len(due_ready), 1)
            self.assertEqual(due_ready[0].team_role_id, team_role_id)

            finalized = storage.finalize_due_team_role_runtime_releases(now="2026-03-26T10:01:10+00:00")
            self.assertEqual(finalized, 1)

            status = storage.get_team_role_runtime_status(team_role_id)
            self.assertIsNotNone(status)
            self.assertEqual(status.status if status else None, "free")
            self.assertEqual(status.last_release_reason if status else None, "response_sent")
            self.assertIsNone(status.preview_text if status else None)

    def test_lock_group_blocks_busy_acquire_across_teams(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "lock.sqlite3")
            tr_a = self._seed_team_role(storage, team_public_id="team-a", role_name="analyst")
            tr_b = self._seed_team_role(storage, team_public_id="team-b", role_name="reviewer")
            storage.ensure_team_role_runtime_status(tr_a)
            storage.ensure_team_role_runtime_status(tr_b)

            lock_group = storage.create_role_lock_group("critical_path")
            storage.add_team_role_to_lock_group(lock_group.lock_group_id, tr_a)
            storage.add_team_role_to_lock_group(lock_group.lock_group_id, tr_b)

            ok_a, acquired_a, blockers_a = storage.try_acquire_team_role_busy(
                tr_a,
                busy_request_id="req-a",
                busy_owner_user_id=1,
                busy_origin="group",
                preview_text="team A task",
                preview_source="user",
                busy_since="2026-03-26T10:00:00+00:00",
                lease_expires_at="2026-03-26T10:30:00+00:00",
            )
            self.assertTrue(ok_a)
            self.assertIsNotNone(acquired_a)
            self.assertEqual(len(blockers_a), 0)

            ok_b, acquired_b, blockers_b = storage.try_acquire_team_role_busy(
                tr_b,
                busy_request_id="req-b",
                busy_owner_user_id=2,
                busy_origin="group",
                preview_text="team B task",
                preview_source="user",
                busy_since="2026-03-26T10:01:00+00:00",
                lease_expires_at="2026-03-26T10:31:00+00:00",
            )
            self.assertFalse(ok_b)
            self.assertIsNone(acquired_b)
            self.assertEqual(len(blockers_b), 1)
            self.assertEqual(blockers_b[0].team_role_id, tr_a)
            self.assertEqual(blockers_b[0].busy_request_id, "req-a")

    def test_stale_lease_is_cleaned_and_new_acquire_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "stale.sqlite3")
            tr_a = self._seed_team_role(storage, team_public_id="team-a", role_name="analyst")
            tr_b = self._seed_team_role(storage, team_public_id="team-b", role_name="reviewer")
            storage.ensure_team_role_runtime_status(tr_a)
            storage.ensure_team_role_runtime_status(tr_b)

            lock_group = storage.create_role_lock_group("shared_pool")
            storage.add_team_role_to_lock_group(lock_group.lock_group_id, tr_a)
            storage.add_team_role_to_lock_group(lock_group.lock_group_id, tr_b)

            storage.mark_team_role_runtime_busy(
                tr_a,
                busy_request_id="req-old",
                busy_owner_user_id=1,
                busy_origin="group",
                preview_text="old task",
                preview_source="user",
                busy_since="2026-03-26T10:00:00+00:00",
                lease_expires_at="2026-03-26T10:05:00+00:00",
                now="2026-03-26T10:00:00+00:00",
            )

            ok_b, acquired_b, blockers_b = storage.try_acquire_team_role_busy(
                tr_b,
                busy_request_id="req-new",
                busy_owner_user_id=2,
                busy_origin="group",
                preview_text="new task",
                preview_source="user",
                busy_since="2026-03-26T10:06:00+00:00",
                lease_expires_at="2026-03-26T10:16:00+00:00",
                now="2026-03-26T10:06:00+00:00",
            )
            self.assertTrue(ok_b)
            self.assertIsNotNone(acquired_b)
            self.assertEqual(len(blockers_b), 0)

            cleaned = storage.get_team_role_runtime_status(tr_a)
            self.assertIsNotNone(cleaned)
            self.assertEqual(cleaned.status if cleaned else None, "free")
            self.assertEqual(cleaned.last_release_reason if cleaned else None, "lease_expired_cleanup")

    @staticmethod
    def _seed_team_role(storage: Storage, *, team_public_id: str, role_name: str) -> int:
        team = storage.upsert_team(public_id=team_public_id, name=team_public_id)
        role = storage.upsert_role(
            role_name=role_name,
            description=f"{role_name} desc",
            base_system_prompt=f"{role_name} prompt",
            extra_instruction=f"{role_name} instruction",
            llm_model=None,
            is_active=True,
        )
        team_role = storage.ensure_team_role(team.team_id, role.role_id)
        if team_role.team_role_id is None:
            raise AssertionError("team_role_id was not assigned")
        return int(team_role.team_role_id)


if __name__ == "__main__":
    unittest.main()
