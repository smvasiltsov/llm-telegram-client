from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.storage import Storage


class PlanSupervisorSkillRunnerIntegrationTests(unittest.TestCase):
    def test_happy_path_with_auto_next_step_and_plan_events_idempotency(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "skill-runner.sqlite3"
            storage = Storage(db)
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9601, "i")
            team_id = int(group.team_id or 0)

            config = {
                "database_path": str(db),
            }

            def run_exec(arguments: dict) -> tuple[int, dict]:
                cmd = [
                    sys.executable,
                    str(root / "scripts" / "skills_runner.py"),
                    "--skills-dir",
                    str(root / "skills"),
                    "exec",
                    "--skill-id",
                    "plan_supervisor",
                    "--arguments-json",
                    json.dumps(arguments, ensure_ascii=False),
                    "--config-json",
                    json.dumps(config, ensure_ascii=False),
                    "--chat-id",
                    str(-9601),
                    "--user-id",
                    "700",
                    "--role-id",
                    "1",
                    "--role-name",
                    "codex",
                ]
                proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
                return proc.returncode, json.loads(proc.stdout)

            _, started = run_exec(
                {
                    "operation": "start_plan",
                    "team_id": team_id,
                    "thread_id": "thr-int",
                    "payload": {
                        "goal": "ship",
                        "steps": [{"step_id": "s1", "title": "Do-1"}, {"step_id": "s2", "title": "Do-2"}],
                    },
                }
            )
            self.assertTrue(started["result"]["ok"])
            run_id = started["result"]["output"]["result"]["plan_run"]["plan_run_id"]
            self.assertIn("Do-1", started["result"]["output"]["directive"])

            _, step1 = run_exec(
                {
                    "operation": "report_step",
                    "team_id": team_id,
                    "thread_id": "thr-int",
                    "payload": {"plan_run_id": run_id, "step_id": "s1", "summary": "ok"},
                }
            )
            self.assertTrue(step1["result"]["ok"])
            self.assertIn("Do-2", step1["result"]["output"]["directive"])

            with storage.transaction(immediate=True):
                e1 = storage.create_plan_event(
                    plan_run_id=str(run_id),
                    step_id="s1",
                    event_type="idem",
                    actor_type="test",
                    idempotency_key="idem-1",
                )
                e2 = storage.create_plan_event(
                    plan_run_id=str(run_id),
                    step_id="s1",
                    event_type="idem",
                    actor_type="test",
                    idempotency_key="idem-1",
                )
            self.assertEqual(e1.event_id, e2.event_id)


if __name__ == "__main__":
    unittest.main()
