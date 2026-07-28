from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skills.plan_supervisor.skill import PlanSupervisorSkill
from skills_sdk.contract import SkillContext
from app.storage import Storage


class PlanSupervisorSkillUnitTests(unittest.TestCase):
    def test_describe_contract_has_operation_and_legacy_command(self) -> None:
        skill = PlanSupervisorSkill()
        spec = skill.describe()
        self.assertEqual(spec.skill_id, "plan_supervisor")
        props = dict(spec.input_schema.get("properties") or {})
        self.assertIn("operation", props)
        self.assertIn("command", props)
        self.assertIn("payload", props)

    def test_validate_config_minimal(self) -> None:
        skill = PlanSupervisorSkill()
        errors = skill.validate_config({"database_path": "./x.sqlite3"})
        self.assertEqual(errors, [])

    def test_routing_supports_legacy_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "skill-unit.sqlite3"
            storage = Storage(db)
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9501, "u")
            team_id = int(group.team_id or 0)

            skill = PlanSupervisorSkill()
            ctx = SkillContext(chain_id="c1", chat_id=-9501, user_id=700, role_id=1, role_name="codex")
            cfg = {
                "database_path": str(db),
                "emit_thread_events": True,
            }

            started = skill.run(
                ctx,
                {
                    "operation": "start_plan",
                    "team_id": team_id,
                    "thread_id": "thr-unit",
                    "payload": {
                        "goal": "g",
                        "steps": [{"step_id": "s1", "title": "t1"}],
                    },
                },
                cfg,
            )
            self.assertTrue(started.ok)
            run_id = started.output["result"]["plan_run"]["plan_run_id"]
            self.assertIn("Приступай к шагу", started.output["directive"])
            q_items, _ = storage.list_thread_questions(thread_id="thr-unit", limit=20)
            a_items, _ = storage.list_thread_answers(thread_id="thr-unit", limit=20)
            self.assertGreaterEqual(len(q_items), 1)
            self.assertGreaterEqual(len(a_items), 1)
            self.assertEqual(str(a_items[0].role_name), "plan_supervisor")

            reported = skill.run(
                ctx,
                {
                    "command": "report_step",
                    "team_id": team_id,
                    "thread_id": "thr-unit",
                    "payload": {"plan_run_id": run_id, "step_id": "s1", "summary": "done"},
                },
                cfg,
            )
            self.assertTrue(reported.ok)
            self.assertEqual(reported.output["operation"], "report_step")
            self.assertIn("План завершен", reported.output["directive"])

    def test_report_step_intent_with_start_payload_is_normalized_to_start_plan(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "skill-unit-normalize.sqlite3"
            storage = Storage(db)
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9502, "u2")
            team_id = int(group.team_id or 0)

            skill = PlanSupervisorSkill()
            ctx = SkillContext(chain_id="c2", chat_id=-9502, user_id=700, role_id=1, role_name="codex")
            cfg = {"database_path": str(db)}

            started = skill.run(
                ctx,
                {
                    "operation": "report_step",
                    "team_id": team_id,
                    "thread_id": "thr-unit-2",
                    "payload": {
                        "goal": "g2",
                        "steps": [{"step_id": "s1", "title": "t1"}],
                    },
                },
                cfg,
            )
            self.assertTrue(started.ok)
            self.assertEqual(started.output["operation"], "start_plan")


if __name__ == "__main__":
    unittest.main()
