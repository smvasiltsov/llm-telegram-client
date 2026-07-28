from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services.plan_supervisor import PlanStepInput, PlanSupervisorService, PlanSupervisorValidationError
from app.storage import Storage


class PlanSupervisorServiceTests(unittest.TestCase):
    def test_fsm_and_projection_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "plan-supervisor.sqlite3")
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9201, "plan")
            team_id = int(group.team_id or 0)

            service = PlanSupervisorService(storage)
            created = service.start_plan(
                team_id=team_id,
                thread_id="thread-1",
                goal="Implement feature",
                steps=[
                    PlanStepInput(step_id="s1", title="Do A"),
                    PlanStepInput(step_id="s2", title="Do B"),
                ],
                actor_role="codex",
                created_by_user_id=700,
                require_manual_approval=True,
            )
            run_id = str(created["plan_run"]["plan_run_id"])

            after_report = service.report_step(plan_run_id=run_id, step_id="s1", summary="done", result="done")
            self.assertEqual(after_report["steps"][0]["status"], "reported")

            after_request = service.request_approval(plan_run_id=run_id, step_id="s1", note="ready")
            self.assertEqual(after_request["steps"][0]["status"], "approval_requested")

            after_approve = service.approve_next(plan_run_id=run_id, step_id="s1", comment="ok")
            self.assertEqual(after_approve["steps"][0]["status"], "done")
            self.assertEqual(after_approve["steps"][1]["status"], "in_progress")
            self.assertEqual(after_approve["ui"]["progress_done"], 1)

            with self.assertRaises(PlanSupervisorValidationError):
                service.approve_next(plan_run_id=run_id, step_id="s1", comment="again")

            with storage.transaction(immediate=True):
                e1 = storage.create_plan_event(
                    plan_run_id=run_id,
                    step_id="s1",
                    event_type="idempotent",
                    actor_type="test",
                    idempotency_key="plan-event-1",
                )
                e2 = storage.create_plan_event(
                    plan_run_id=run_id,
                    step_id="s1",
                    event_type="idempotent",
                    actor_type="test",
                    idempotency_key="plan-event-1",
                )
            self.assertEqual(e1.event_id, e2.event_id)


if __name__ == "__main__":
    unittest.main()
