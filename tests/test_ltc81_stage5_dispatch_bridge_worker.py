from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.interfaces.api.qa_dispatch_bridge_worker import (
    BridgeExecutionResult,
    QaPostAnswerDispatchItem,
    QaPostAnswerDispatchPlan,
    QaDispatchBridgeWorker,
    _map_execution_failure,
    _resolve_execution_auth_token,
    _resolve_execution_session,
    _resolve_role_requires_auth,
)
from app.storage import Storage


class _FakeMetricsPort:
    def __init__(self) -> None:
        self.increment_calls: list[tuple[str, dict | None, int | float | None]] = []
        self.observe_calls: list[tuple[str, dict | None, float]] = []

    def increment(self, *args, **kwargs):  # noqa: ANN002, ANN003
        name = str(args[0]) if args else str(kwargs.get("name", ""))
        labels = kwargs.get("labels")
        value = kwargs.get("value")
        self.increment_calls.append((name, labels, value))

    def observe_ms(self, *args, **kwargs):  # noqa: ANN002, ANN003
        name = str(args[0]) if args else str(kwargs.get("name", ""))
        labels = kwargs.get("labels")
        value = float(kwargs.get("value_ms", 0.0))
        self.observe_calls.append((name, labels, value))


class _DummyCipher:
    def decrypt(self, encrypted_token: str) -> str:
        return str(encrypted_token)


class LTC81Stage5DispatchBridgeWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.storage = Storage(Path(self._tmp.name) / "ltc81.sqlite3")
        with self.storage.transaction(immediate=True):
            group = self.storage.upsert_group(-9810, "bridge-worker")
            role = self.storage.upsert_role(
                role_name="dev",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            self.storage.ensure_group_role(group.group_id, role.role_id)
            self.team_id = int(group.team_id or 0)
            self.role_id = int(role.role_id)
            self.team_role_id = int(self.storage.resolve_team_role_id(self.team_id, self.role_id, ensure_exists=True) or 0)
            if self.team_role_id <= 0:
                raise AssertionError("team_role_id missing")

    async def _wait_for_status(self, question_id: str, status: str, timeout_sec: float = 4.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout_sec
        while asyncio.get_running_loop().time() < deadline:
            item = self.storage.get_question(question_id)
            if item is not None and item.status == status:
                return
            await asyncio.sleep(0.05)
        raise AssertionError(f"Question {question_id} did not reach status={status}")

    async def test_event_driven_enqueue_reaches_answered_with_persisted_answer_and_feed(self) -> None:
        with self.storage.transaction(immediate=True):
            self.storage.create_question(
                question_id="q-worker-1",
                thread_id="t-worker-1",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="hello",
                status="accepted",
            )

        async def _executor(_runtime, _question, _correlation_id):
            return BridgeExecutionResult(
                answer_text="world",
                role_name="dev",
                answer_team_role_id=self.team_role_id,
                append_orchestrator_feed=True,
            )

        metrics = _FakeMetricsPort()
        runtime = SimpleNamespace(storage=self.storage, metrics_port=metrics)
        worker = QaDispatchBridgeWorker(
            runtime=runtime,
            execute_question_fn=_executor,
            sweep_interval_sec=0.05,
            max_parallelism=2,
            claim_batch_size=10,
        )
        await worker.start()
        self.addAsyncCleanup(worker.stop)

        worker.enqueue_question("q-worker-1")
        await self._wait_for_status("q-worker-1", "answered")

        answer = self.storage.get_latest_answer_for_question("q-worker-1")
        self.assertIsNotNone(answer)
        self.assertEqual(answer.text if answer else None, "world")
        feed, _ = self.storage.list_orchestrator_feed(team_id=self.team_id, limit=10)
        self.assertTrue(any(item.question_id == "q-worker-1" for item in feed))
        self.assertTrue(
            any(
                name == "runtime_operations_total"
                and isinstance(labels, dict)
                and labels.get("result") == "answered"
                for name, labels, _ in metrics.increment_calls
            )
        )

    async def test_polling_sweep_claims_and_processes_without_explicit_enqueue(self) -> None:
        with self.storage.transaction(immediate=True):
            self.storage.create_question(
                question_id="q-worker-2",
                thread_id="t-worker-2",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="hello",
                status="accepted",
            )

        async def _executor(_runtime, _question, _correlation_id):
            return BridgeExecutionResult(
                answer_text="done",
                role_name="dev",
                answer_team_role_id=self.team_role_id,
                append_orchestrator_feed=False,
            )

        runtime = SimpleNamespace(storage=self.storage, metrics_port=_FakeMetricsPort())
        worker = QaDispatchBridgeWorker(
            runtime=runtime,
            execute_question_fn=_executor,
            sweep_interval_sec=0.05,
            max_parallelism=2,
            claim_batch_size=10,
        )
        await worker.start()
        self.addAsyncCleanup(worker.stop)

        await self._wait_for_status("q-worker-2", "answered")

    async def test_parallelism_is_limited_per_team_role(self) -> None:
        with self.storage.transaction(immediate=True):
            self.storage.create_question(
                question_id="q-worker-3a",
                thread_id="t-worker-3",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="a",
                status="accepted",
            )
            self.storage.create_question(
                question_id="q-worker-3b",
                thread_id="t-worker-3",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="b",
                status="accepted",
            )

        state = {"running": 0, "max_running": 0}

        async def _executor(_runtime, _question, _correlation_id):
            state["running"] += 1
            state["max_running"] = max(state["max_running"], state["running"])
            await asyncio.sleep(0.1)
            state["running"] -= 1
            return BridgeExecutionResult(
                answer_text="ok",
                role_name="dev",
                answer_team_role_id=self.team_role_id,
                append_orchestrator_feed=False,
            )

        runtime = SimpleNamespace(storage=self.storage, metrics_port=_FakeMetricsPort())
        worker = QaDispatchBridgeWorker(
            runtime=runtime,
            execute_question_fn=_executor,
            sweep_interval_sec=0.05,
            max_parallelism=4,
            claim_batch_size=10,
        )
        await worker.start()
        self.addAsyncCleanup(worker.stop)

        worker.enqueue_question("q-worker-3a")
        worker.enqueue_question("q-worker-3b")
        await self._wait_for_status("q-worker-3a", "answered")
        await self._wait_for_status("q-worker-3b", "answered")

        self.assertLessEqual(int(state["max_running"]), 1)

    async def test_retry_metric_is_emitted_on_requeue(self) -> None:
        with self.storage.transaction(immediate=True):
            self.storage.create_question(
                question_id="q-worker-retry",
                thread_id="t-worker-retry",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="retry",
                status="accepted",
            )

        state = {"count": 0}

        async def _executor(_runtime, _question, _correlation_id):
            state["count"] += 1
            if state["count"] == 1:
                raise RuntimeError("provider timeout")
            return BridgeExecutionResult(
                answer_text="ok-after-retry",
                role_name="dev",
                answer_team_role_id=self.team_role_id,
                append_orchestrator_feed=False,
            )

        metrics = _FakeMetricsPort()
        worker = QaDispatchBridgeWorker(
            runtime=SimpleNamespace(storage=self.storage, metrics_port=metrics),
            execute_question_fn=_executor,
            sweep_interval_sec=0.05,
            max_parallelism=1,
            claim_batch_size=10,
            max_attempts=3,
            retry_delay_sec=0,
        )
        await worker.start()
        self.addAsyncCleanup(worker.stop)

        worker.enqueue_question("q-worker-retry")
        await self._wait_for_status("q-worker-retry", "answered")

        retry_metrics = [
            (name, labels)
            for name, labels, _ in metrics.increment_calls
            if name == "runtime_operations_total" and isinstance(labels, dict) and labels.get("result") == "retry"
        ]
        self.assertGreaterEqual(len(retry_metrics), 1)

    async def test_long_running_execution_keeps_lease_alive_and_does_not_expire(self) -> None:
        with self.storage.transaction(immediate=True):
            self.storage.create_question(
                question_id="q-worker-long-lease",
                thread_id="t-worker-long-lease",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="long run",
                status="accepted",
            )

        async def _executor(_runtime, _question, _correlation_id):
            await asyncio.sleep(1.6)
            return BridgeExecutionResult(
                answer_text="long-ok",
                role_name="dev",
                answer_team_role_id=self.team_role_id,
                append_orchestrator_feed=False,
            )

        worker = QaDispatchBridgeWorker(
            runtime=SimpleNamespace(storage=self.storage, metrics_port=_FakeMetricsPort()),
            execute_question_fn=_executor,
            sweep_interval_sec=0.05,
            max_parallelism=1,
            claim_batch_size=10,
            lease_ttl_sec=1,
            max_attempts=3,
            retry_delay_sec=0,
        )
        await worker.start()
        self.addAsyncCleanup(worker.stop)

        worker.enqueue_question("q-worker-long-lease")
        await self._wait_for_status("q-worker-long-lease", "answered", timeout_sec=6.0)
        self.assertEqual(self.storage.get_qa_dispatch_attempt_count("q-worker-long-lease"), 1)

    def test_map_execution_failure_codes(self) -> None:
        self.assertEqual(_map_execution_failure(RuntimeError("dispatch_rejected:no_token"))[0], "dispatch_rejected")
        self.assertEqual(_map_execution_failure(RuntimeError("runtime_busy_conflict"))[0], "runtime_busy_conflict")
        self.assertEqual(_map_execution_failure(asyncio.TimeoutError())[0], "provider_timeout")
        self.assertEqual(_map_execution_failure(RuntimeError("Execution attempt lease expired"))[0], "runtime_dispatch_timeout")
        self.assertEqual(_map_execution_failure(RuntimeError("provider http 500"))[0], "provider_error")
        self.assertEqual(_map_execution_failure(RuntimeError("unexpected boom"))[0], "internal_execution_error")

    def test_resolve_execution_auth_token_falls_back_to_owner(self) -> None:
        with self.storage.transaction(immediate=True):
            self.storage.create_question(
                question_id="q-worker-auth-fallback",
                thread_id="t-worker-auth-fallback",
                team_id=self.team_id,
                created_by_user_id=999,
                target_team_role_id=self.team_role_id,
                text="auth fallback",
                status="accepted",
            )
            # created_by user has no authorized token
            self.storage.upsert_auth_token(999, "enc-missing")
            self.storage.reset_authorizations()
            # owner token is valid and must be used by bridge fallback
            self.storage.upsert_user(700, "owner")
            self.storage.upsert_auth_token(700, "enc-owner")

        question = self.storage.get_question("q-worker-auth-fallback")
        self.assertIsNotNone(question)
        runtime = SimpleNamespace(storage=self.storage, owner_user_id=700)
        user_id, token = _resolve_execution_auth_token(runtime, question, "corr-test")
        self.assertEqual(user_id, 700)
        self.assertIsNotNone(token)
        self.assertEqual(token.telegram_user_id, 700)

    def test_resolve_execution_session_skips_token_for_auth_mode_none(self) -> None:
        with self.storage.transaction(immediate=True):
            self.storage.create_question(
                question_id="q-worker-auth-none",
                thread_id="t-worker-auth-none",
                team_id=self.team_id,
                created_by_user_id=999,
                target_team_role_id=self.team_role_id,
                text="auth none",
                status="accepted",
            )
        question = self.storage.get_question("q-worker-auth-none")
        self.assertIsNotNone(question)
        role = self.storage.get_role_by_id(self.role_id)
        runtime = SimpleNamespace(
            storage=self.storage,
            owner_user_id=700,
            provider_registry={"p1": SimpleNamespace(auth_mode="none")},
            default_provider_id="p1",
            provider_models=[],
            provider_model_map={},
            cipher=_DummyCipher(),
        )
        user_id, session_token = _resolve_execution_session(
            runtime=runtime,
            question=question,
            team_id=self.team_id,
            role=role,
            correlation_id="corr-none",
        )
        self.assertEqual(user_id, 999)
        self.assertEqual(session_token, "")

    def test_resolve_execution_session_requires_token_for_auth_mode_required(self) -> None:
        with self.storage.transaction(immediate=True):
            self.storage.create_question(
                question_id="q-worker-auth-required",
                thread_id="t-worker-auth-required",
                team_id=self.team_id,
                created_by_user_id=999,
                target_team_role_id=self.team_role_id,
                text="auth required",
                status="accepted",
            )
            self.storage.reset_authorizations()
        question = self.storage.get_question("q-worker-auth-required")
        self.assertIsNotNone(question)
        role = self.storage.get_role_by_id(self.role_id)
        runtime = SimpleNamespace(
            storage=self.storage,
            owner_user_id=700,
            provider_registry={"p1": SimpleNamespace(auth_mode="required")},
            default_provider_id="p1",
            provider_models=[],
            provider_model_map={},
            cipher=_DummyCipher(),
        )
        with self.assertRaisesRegex(RuntimeError, "dispatch_rejected:missing_authorized_token"):
            _resolve_execution_session(
                runtime=runtime,
                question=question,
                team_id=self.team_id,
                role=role,
                correlation_id="corr-required",
            )

    def test_resolve_role_requires_auth_fail_safe_required(self) -> None:
        role = self.storage.get_role_by_id(self.role_id)
        runtime = SimpleNamespace(
            storage=self.storage,
            provider_registry={},
            default_provider_id="missing-provider",
            provider_models=[],
            provider_model_map={},
        )
        self.assertTrue(
            _resolve_role_requires_auth(
                runtime=runtime,
                team_id=self.team_id,
                role=role,
                correlation_id="corr-failsafe",
            )
        )

    def test_build_post_answer_dispatch_plan_includes_tagged_role(self) -> None:
        with self.storage.transaction(immediate=True):
            worker_role = self.storage.upsert_role(
                role_name="worker2",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            self.storage.ensure_team_role(self.team_id, worker_role.role_id)
            question = self.storage.create_question(
                question_id="q-plan-mention",
                thread_id="t-plan",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="ask",
                status="in_progress",
                origin_type="user",
            )
            self.storage.create_answer(
                answer_id="a-plan-mention",
                question_id=question.question_id,
                thread_id=question.thread_id,
                team_id=question.team_id,
                team_role_id=self.team_role_id,
                role_name="dev",
                text="call @worker2",
            )

        worker = QaDispatchBridgeWorker(
            runtime=SimpleNamespace(storage=self.storage, metrics_port=_FakeMetricsPort()),
            execute_question_fn=lambda *_args, **_kwargs: None,  # type: ignore[arg-type]
        )
        plan = worker._build_post_answer_dispatch_plan(
            question=question,
            answer_id="a-plan-mention",
            answer_text="call @worker2",
        )
        mention_items = [item for item in plan.items if item.reason == "mention_tag"]
        self.assertEqual(len(mention_items), 1)
        self.assertNotEqual(int(mention_items[0].target_team_role_id), int(self.team_role_id))

    def test_build_post_answer_dispatch_plan_includes_orchestrator_events_for_direct_request(self) -> None:
        with self.storage.transaction(immediate=True):
            orch_role = self.storage.upsert_role(
                role_name="orch",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            self.storage.ensure_team_role(self.team_id, orch_role.role_id)
            self.storage.set_team_role_mode(self.team_id, orch_role.role_id, "orchestrator")
            orch_team_role_id = int(self.storage.resolve_team_role_id(self.team_id, orch_role.role_id, ensure_exists=True) or 0)
            question = self.storage.create_question(
                question_id="q-plan-orch",
                thread_id="t-plan-orch",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="user to dev",
                status="in_progress",
                origin_type="user",
            )
            self.storage.create_answer(
                answer_id="a-plan-orch",
                question_id=question.question_id,
                thread_id=question.thread_id,
                team_id=question.team_id,
                team_role_id=self.team_role_id,
                role_name="dev",
                text="role answer",
            )

        worker = QaDispatchBridgeWorker(
            runtime=SimpleNamespace(storage=self.storage, metrics_port=_FakeMetricsPort()),
            execute_question_fn=lambda *_args, **_kwargs: None,  # type: ignore[arg-type]
        )
        plan = worker._build_post_answer_dispatch_plan(
            question=question,
            answer_id="a-plan-orch",
            answer_text="role answer",
        )
        reasons = [item.reason for item in plan.items]
        self.assertIn("orchestrator_user_event", reasons)
        self.assertIn("orchestrator_answer_event", reasons)
        for item in plan.items:
            if item.reason.startswith("orchestrator_"):
                self.assertEqual(int(item.target_team_role_id), orch_team_role_id)

    def test_dispatch_post_answer_plan_creates_child_question_once(self) -> None:
        with self.storage.transaction(immediate=True):
            target_role = self.storage.upsert_role(
                role_name="worker3",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            self.storage.ensure_team_role(self.team_id, target_role.role_id)
            target_team_role_id = int(self.storage.resolve_team_role_id(self.team_id, target_role.role_id, ensure_exists=True) or 0)
            parent_question = self.storage.create_question(
                question_id="q-dispatch-parent",
                thread_id="t-dispatch",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="root",
                status="answered",
                origin_type="user",
            )
            self.storage.create_answer(
                answer_id="a-dispatch-parent",
                question_id=parent_question.question_id,
                thread_id=parent_question.thread_id,
                team_id=parent_question.team_id,
                team_role_id=self.team_role_id,
                role_name="dev",
                text="mention @worker3",
            )

        worker = QaDispatchBridgeWorker(
            runtime=SimpleNamespace(storage=self.storage, metrics_port=_FakeMetricsPort()),
            execute_question_fn=lambda *_args, **_kwargs: None,  # type: ignore[arg-type]
        )
        plan = QaPostAnswerDispatchPlan(
            items=(
                QaPostAnswerDispatchItem(
                    target_team_role_id=target_team_role_id,
                    text="follow-up for @worker3",
                    reason="mention_tag",
                    origin_type="role_dispatch",
                    parent_question_id=parent_question.question_id,
                    parent_answer_id="a-dispatch-parent",
                ),
            )
        )

        worker._dispatch_post_answer_plan(
            correlation_id="corr-dispatch",
            parent_question=parent_question,
            plan=plan,
        )
        worker._dispatch_post_answer_plan(
            correlation_id="corr-dispatch",
            parent_question=parent_question,
            plan=plan,
        )

        items, _ = self.storage.list_qa_journal(team_id=self.team_id, team_role_id=target_team_role_id, limit=20)
        children = [q for q in items if q.source_question_id == parent_question.question_id and q.origin_type == "role_dispatch"]
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].parent_answer_id, "a-dispatch-parent")

    def test_dispatch_post_answer_plan_creates_orchestrator_events_once(self) -> None:
        with self.storage.transaction(immediate=True):
            orch_role = self.storage.upsert_role(
                role_name="orch2",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            self.storage.ensure_team_role(self.team_id, orch_role.role_id)
            self.storage.set_team_role_mode(self.team_id, orch_role.role_id, "orchestrator")
            orch_team_role_id = int(self.storage.resolve_team_role_id(self.team_id, orch_role.role_id, ensure_exists=True) or 0)
            parent_question = self.storage.create_question(
                question_id="q-dispatch-orch-parent",
                thread_id="t-dispatch-orch",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="user text to role",
                status="answered",
                origin_type="user",
            )
            self.storage.create_answer(
                answer_id="a-dispatch-orch-parent",
                question_id=parent_question.question_id,
                thread_id=parent_question.thread_id,
                team_id=parent_question.team_id,
                team_role_id=self.team_role_id,
                role_name="dev",
                text="role answer text",
            )

        worker = QaDispatchBridgeWorker(
            runtime=SimpleNamespace(storage=self.storage, metrics_port=_FakeMetricsPort()),
            execute_question_fn=lambda *_args, **_kwargs: None,  # type: ignore[arg-type]
        )
        plan = worker._build_post_answer_dispatch_plan(
            question=parent_question,
            answer_id="a-dispatch-orch-parent",
            answer_text="role answer text",
        )
        worker._dispatch_post_answer_plan(
            correlation_id="corr-dispatch-orch",
            parent_question=parent_question,
            plan=plan,
        )
        worker._dispatch_post_answer_plan(
            correlation_id="corr-dispatch-orch",
            parent_question=parent_question,
            plan=plan,
        )

        items, _ = self.storage.list_qa_journal(team_id=self.team_id, team_role_id=orch_team_role_id, limit=30)
        children = [q for q in items if q.source_question_id == parent_question.question_id and q.origin_type == "orchestrator"]
        self.assertEqual(len(children), 2)
        texts = {str(q.text) for q in children}
        self.assertIn("user text to role", texts)
        self.assertIn("role answer text", texts)
        for child in children:
            self.assertEqual(child.parent_answer_id, "a-dispatch-orch-parent")

    def test_dispatch_post_answer_plan_skips_when_max_hops_reached(self) -> None:
        with self.storage.transaction(immediate=True):
            target_role = self.storage.upsert_role(
                role_name="hop_target",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            self.storage.ensure_team_role(self.team_id, target_role.role_id)
            target_team_role_id = int(self.storage.resolve_team_role_id(self.team_id, target_role.role_id, ensure_exists=True) or 0)

            q0 = self.storage.create_question(
                question_id="q-hop-0",
                thread_id="t-hop",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="root",
                status="answered",
                origin_type="user",
            )
            q1 = self.storage.create_question(
                question_id="q-hop-1",
                thread_id="t-hop",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="child1",
                status="answered",
                origin_type="role_dispatch",
                source_question_id=q0.question_id,
            )
            q2 = self.storage.create_question(
                question_id="q-hop-2",
                thread_id="t-hop",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="child2",
                status="answered",
                origin_type="role_dispatch",
                source_question_id=q1.question_id,
            )
            self.storage.create_answer(
                answer_id="a-hop-2",
                question_id=q2.question_id,
                thread_id=q2.thread_id,
                team_id=q2.team_id,
                team_role_id=self.team_role_id,
                role_name="dev",
                text="mention @hop_target",
            )

        runtime = SimpleNamespace(storage=self.storage, metrics_port=_FakeMetricsPort(), qa_post_answer_max_hops=2)
        worker = QaDispatchBridgeWorker(
            runtime=runtime,
            execute_question_fn=lambda *_args, **_kwargs: None,  # type: ignore[arg-type]
        )
        plan = QaPostAnswerDispatchPlan(
            items=(
                QaPostAnswerDispatchItem(
                    target_team_role_id=target_team_role_id,
                    text="mention @hop_target",
                    reason="mention_tag",
                    origin_type="role_dispatch",
                    parent_question_id="q-hop-2",
                    parent_answer_id="a-hop-2",
                ),
            )
        )
        worker._dispatch_post_answer_plan(
            correlation_id="corr-hop",
            parent_question=q2,
            plan=plan,
        )
        items, _ = self.storage.list_qa_journal(team_id=self.team_id, team_role_id=target_team_role_id, limit=20)
        children = [q for q in items if q.source_question_id == "q-hop-2"]
        self.assertEqual(children, [])

    def test_build_post_answer_dispatch_plan_respects_fanout_limit(self) -> None:
        with self.storage.transaction(immediate=True):
            role_names: list[str] = []
            for idx in range(1, 6):
                name = f"fan_{idx}"
                role = self.storage.upsert_role(
                    role_name=name,
                    description="d",
                    base_system_prompt="sp",
                    extra_instruction="ei",
                    llm_model=None,
                    is_active=True,
                )
                self.storage.ensure_team_role(self.team_id, role.role_id)
                role_names.append(name)
            q = self.storage.create_question(
                question_id="q-fanout",
                thread_id="t-fanout",
                team_id=self.team_id,
                created_by_user_id=700,
                target_team_role_id=self.team_role_id,
                text="root",
                status="answered",
                origin_type="user",
            )

        runtime = SimpleNamespace(storage=self.storage, metrics_port=_FakeMetricsPort(), qa_post_answer_max_fanout=2)
        worker = QaDispatchBridgeWorker(
            runtime=runtime,
            execute_question_fn=lambda *_args, **_kwargs: None,  # type: ignore[arg-type]
        )
        answer_text = " ".join(f"@{name}" for name in role_names)
        plan = worker._build_post_answer_dispatch_plan(
            question=q,
            answer_id="a-fanout",
            answer_text=answer_text,
        )
        mention_items = [item for item in plan.items if item.reason == "mention_tag"]
        self.assertLessEqual(len(mention_items), 2)


if __name__ == "__main__":
    unittest.main()
