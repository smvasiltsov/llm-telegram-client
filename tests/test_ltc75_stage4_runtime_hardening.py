from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.application.use_cases.write_api import TeamRolePatchRequest, patch_team_role_result
from app.storage import Storage


class LTC75Stage4RuntimeHardeningTests(unittest.TestCase):
    def test_rollback_drill_partial_fail_then_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "ltc75_stage4.sqlite3")
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9751, "stage4")
                role = storage.upsert_role(
                    role_name="dev",
                    description="d",
                    base_system_prompt="sp",
                    extra_instruction="ei",
                    llm_model=None,
                    is_active=True,
                )
                team_id = int(group.team_id or 0)
                storage.bind_master_role_to_team(team_id, role.role_id)
                original = storage.get_team_role(team_id, role.role_id)

            def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
                _ = (args, kwargs)
                raise RuntimeError("forced_failure")

            with patch.object(storage, "set_team_role_model", side_effect=_boom):
                failed = patch_team_role_result(
                    storage,
                    team_id=team_id,
                    role_id=role.role_id,
                    patch=TeamRolePatchRequest(display_name="TempName", model_override="provider:model"),
                )
            self.assertTrue(failed.is_error)

            current_after_fail = storage.get_team_role(team_id, role.role_id)
            self.assertEqual(current_after_fail.display_name, original.display_name)
            self.assertEqual(current_after_fail.model_override, original.model_override)

            recovered = patch_team_role_result(
                storage,
                team_id=team_id,
                role_id=role.role_id,
                patch=TeamRolePatchRequest(display_name="RecoveredName"),
            )
            self.assertTrue(recovered.is_ok)
            current_after_recovery = storage.get_team_role(team_id, role.role_id)
            self.assertEqual(current_after_recovery.display_name, "RecoveredName")


if __name__ == "__main__":
    unittest.main()
