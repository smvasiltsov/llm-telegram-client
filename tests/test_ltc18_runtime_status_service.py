from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services.role_runtime_status import RoleRuntimeStatusService
from app.storage import Storage


class LTC18RuntimeStatusServiceTests(unittest.TestCase):
    def test_sanitize_preview_uses_user_text_and_truncates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            service = RoleRuntimeStatusService(Storage(Path(td) / "preview.sqlite3"))
            preview = service.sanitize_preview(
                'INPUT_JSON: {"system_prompt":"hidden","instruction":"hidden","user_text":"'
                + ("A" * 140)
                + '"}',
                source="user",
            )
            self.assertIsNotNone(preview)
            text = str(preview or "")
            self.assertEqual(len(text), 100)
            self.assertNotIn("{", text)
            self.assertNotIn("hidden", text)

    def test_acquire_busy_respects_lock_group_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "service.sqlite3")
            service = RoleRuntimeStatusService(storage, busy_lease_seconds=120)
            tr_a = self._seed_team_role(storage, team_public_id="team-a", role_name="analyst")
            tr_b = self._seed_team_role(storage, team_public_id="team-b", role_name="reviewer")

            lock_group = storage.create_role_lock_group("shared")
            storage.add_team_role_to_lock_group(lock_group.lock_group_id, tr_a)
            storage.add_team_role_to_lock_group(lock_group.lock_group_id, tr_b)

            a = service.acquire_busy(
                team_role_id=tr_a,
                busy_request_id="req-a",
                busy_owner_user_id=10,
                busy_origin="group",
                preview_text="team A task",
                preview_source="user",
            )
            self.assertTrue(a.acquired)

            b = service.acquire_busy(
                team_role_id=tr_b,
                busy_request_id="req-b",
                busy_owner_user_id=11,
                busy_origin="group",
                preview_text="team B task",
                preview_source="user",
            )
            self.assertFalse(b.acquired)
            self.assertEqual(len(b.blockers), 1)
            self.assertEqual(b.blockers[0].team_role_id, tr_a)

            service.release_busy(team_role_id=tr_a, release_reason="response_sent")
            c = service.acquire_busy(
                team_role_id=tr_b,
                busy_request_id="req-c",
                busy_owner_user_id=11,
                busy_origin="group",
                preview_text='SKILL_RESULT: {"summary":"done"}',
                preview_source="skill_engine",
            )
            self.assertTrue(c.acquired)
            current = service.get_status(team_role_id=tr_b)
            self.assertEqual(current.preview_text, "done")

    def test_release_busy_uses_delay_and_preserves_preview_until_finalized(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "delay.sqlite3")
            service = RoleRuntimeStatusService(storage, free_transition_delay_sec=15)
            tr = self._seed_team_role(storage, team_public_id="team-a", role_name="analyst")
            service.acquire_busy(
                team_role_id=tr,
                busy_request_id="req-1",
                busy_owner_user_id=10,
                busy_origin="group",
                preview_text="Delay me",
                preview_source="user",
            )

            release_marked = service.release_busy(team_role_id=tr, release_reason="response_sent")
            self.assertEqual(release_marked.status, "busy")
            self.assertEqual(release_marked.preview_text, "Delay me")
            self.assertEqual(release_marked.free_release_reason_pending, "response_sent")
            self.assertIsNotNone(release_marked.free_release_delay_until)

            due_now = service.finalize_due_releases(now="2000-01-01T00:00:00+00:00")
            self.assertEqual(due_now, 0)

            finalized = service.finalize_due_releases(now="2999-01-01T00:00:00+00:00", limit=100)
            self.assertEqual(finalized, 1)
            status = service.get_status(team_role_id=tr)
            self.assertEqual(status.status, "free")
            self.assertEqual(status.last_release_reason, "response_sent")
            self.assertIsNone(status.preview_text)

    def test_cleanup_stale_busy_uses_delay_before_free(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "stale_delay.sqlite3")
            service = RoleRuntimeStatusService(storage, busy_lease_seconds=30, free_transition_delay_sec=20)
            tr = self._seed_team_role(storage, team_public_id="team-a", role_name="analyst")
            storage.mark_team_role_runtime_busy(
                tr,
                busy_request_id="req-stale",
                busy_owner_user_id=1,
                busy_origin="group",
                preview_text="stale task",
                preview_source="user",
                busy_since="2026-03-26T10:00:00+00:00",
                lease_expires_at="2026-03-26T10:00:30+00:00",
                now="2026-03-26T10:00:00+00:00",
            )

            changed = storage.cleanup_stale_busy_team_roles(
                now="2026-03-26T10:00:31+00:00",
                free_transition_delay_sec=20,
            )
            self.assertEqual(changed, 1)
            pending = service.get_status(team_role_id=tr)
            self.assertEqual(pending.status, "busy")
            self.assertEqual(pending.free_release_reason_pending, "lease_expired_cleanup")

            finalized = service.finalize_due_releases(now="2026-03-26T10:00:51+00:00")
            self.assertEqual(finalized, 1)
            released = service.get_status(team_role_id=tr)
            self.assertEqual(released.status, "free")
            self.assertEqual(released.last_release_reason, "lease_expired_cleanup")

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
