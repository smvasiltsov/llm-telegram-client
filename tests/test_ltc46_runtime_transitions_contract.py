from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.application.contracts import RuntimeOperation
from app.application.use_cases.runtime_orchestration import (
    RUNTIME_OPERATION_TRANSITION_TABLE,
    execute_run_chain_operation,
)


class LTC46RuntimeTransitionsContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_transition_table_covers_priority_operations(self) -> None:
        ops = {row["operation"] for row in RUNTIME_OPERATION_TRANSITION_TABLE}
        self.assertIn(RuntimeOperation.RUN_CHAIN.value, ops)
        self.assertIn(RuntimeOperation.DISPATCH_MENTIONS.value, ops)
        self.assertIn(RuntimeOperation.ORCHESTRATOR_POST_EVENT.value, ops)
        self.assertIn(RuntimeOperation.PENDING_REPLAY.value, ops)

    async def test_success_path_transitions_to_free(self) -> None:
        async def run_chain_stub(**_: object) -> SimpleNamespace:
            return SimpleNamespace(completed_roles=1, had_error=False, stopped=False)

        result = await execute_run_chain_operation(
            context=object(),
            team_id=1,
            chat_id=2,
            user_id=3,
            session_token="s",
            roles=[],
            user_text="u",
            reply_text=None,
            actor_username="user",
            reply_to_message_id=10,
            is_all=False,
            apply_plugins=True,
            save_pending_on_unauthorized=False,
            run_chain_fn=run_chain_stub,
        )
        self.assertTrue(result.is_ok)
        self.assertTrue(bool(result.value and result.value.completed))
        states = [(t.from_state, t.to_state) for t in (result.value.transitions if result.value else ())]
        self.assertIn(("queued", "busy"), states)
        self.assertIn(("busy", "free"), states)

    async def test_pending_replay_error_transitions_to_pending(self) -> None:
        async def run_chain_stub(**_: object) -> SimpleNamespace:
            return SimpleNamespace(completed_roles=0, had_error=True, stopped=True)

        result = await execute_run_chain_operation(
            context=object(),
            team_id=1,
            chat_id=2,
            user_id=3,
            session_token="s",
            roles=[],
            user_text="u",
            reply_text=None,
            actor_username="user",
            reply_to_message_id=10,
            is_all=False,
            apply_plugins=False,
            save_pending_on_unauthorized=False,
            chain_origin="pending",
            operation=RuntimeOperation.PENDING_REPLAY,
            run_chain_fn=run_chain_stub,
        )
        self.assertTrue(result.is_ok)
        self.assertTrue(bool(result.value and result.value.replay_scheduled))
        reasons = [t.reason for t in (result.value.transitions if result.value else ())]
        states = [(t.from_state, t.to_state) for t in (result.value.transitions if result.value else ())]
        self.assertIn(("busy", "pending"), states)
        self.assertIn("replay_failed", reasons)


if __name__ == "__main__":
    unittest.main()
