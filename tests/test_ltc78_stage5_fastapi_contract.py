from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.application.authz import OwnerOnlyAuthzService
from app.role_catalog import RoleCatalog
from app.services.role_runtime_status import RoleRuntimeStatusService
from app.storage import Storage

_IMPORT_ERROR: Exception | None = None
try:
    from fastapi.testclient import TestClient
except Exception as exc:  # pragma: no cover - dependency gap in environment
    _IMPORT_ERROR = exc


class _FakeMetricsPort:
    def increment(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)

    def observe_ms(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)

    def operation_timer(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = (args, kwargs)
        return None


class LTC78Stage5FastApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        if _IMPORT_ERROR is not None:
            self.skipTest(f"fastapi test dependencies are unavailable: {_IMPORT_ERROR}")
        try:
            from app.interfaces.api.read_only_app import build_read_only_fastapi_app as builder
        except Exception as exc:
            self.skipTest(f"api transport dependencies are unavailable: {exc}")
        self._builder = builder

    def _client(self) -> TestClient:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root = Path(td.name)
        catalog_dir = root / "roles"
        catalog_dir.mkdir(parents=True, exist_ok=True)
        (catalog_dir / "dev.json").write_text(
            (
                '{"schema_version":1,"role_name":"dev","description":"Developer",'
                '"base_system_prompt":"p","extra_instruction":"i","llm_model":"gpt","is_active":true}\n'
            ),
            encoding="utf-8",
        )
        role_catalog = RoleCatalog.load(catalog_dir)
        storage = Storage(root / "ltc78_api.sqlite3")
        storage.attach_role_catalog(role_catalog)
        with storage.transaction(immediate=True):
            group = storage.upsert_group(-9781, "g")
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
            team_role_id = int(storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True) or 0)
            if team_role_id <= 0:
                raise AssertionError("team_role_id missing")
            q = storage.create_question(
                question_id="q-ready",
                thread_id="t-ready",
                team_id=team_id,
                created_by_user_id=700,
                target_team_role_id=team_role_id,
                text="hello",
            )
            storage.transition_question_status(question_id=q.question_id, status="queued")
            storage.transition_question_status(question_id=q.question_id, status="in_progress")
            a = storage.create_answer(
                answer_id="a-ready",
                question_id=q.question_id,
                thread_id=q.thread_id,
                team_id=q.team_id,
                team_role_id=team_role_id,
                role_name="dev",
                text="world",
            )
            storage.transition_question_status(question_id=q.question_id, status="answered")
            storage.append_orchestrator_feed_item(
                team_id=team_id,
                thread_id=q.thread_id,
                question_id=q.question_id,
                answer_id=a.answer_id,
            )
        runtime = SimpleNamespace(
            storage=storage,
            role_runtime_status_service=RoleRuntimeStatusService(storage, free_transition_delay_sec=0),
            role_dispatch_queue_service=SimpleNamespace(),
            free_transition_delay_sec=0,
            authz_service=OwnerOnlyAuthzService(owner_user_id=700),
            metrics_port=_FakeMetricsPort(),
            role_catalog=role_catalog,
        )
        app = self._builder(runtime)
        return TestClient(app)

    def _team_id_and_role_id(self, client: TestClient) -> tuple[int, int]:
        teams = client.get("/api/v1/teams", headers={"X-Owner-User-Id": "700"}).json()
        team_id = int(teams["items"][0]["team_id"])
        roles = client.get(f"/api/v1/teams/{team_id}/roles", headers={"X-Owner-User-Id": "700"}).json()
        role_id = int(roles[0]["role_id"])
        return team_id, role_id

    def test_post_questions_returns_202_and_idempotent_replay(self) -> None:
        client = self._client()
        team_id, role_id = self._team_id_and_role_id(client)
        team_role_id = int(client.app.state.runtime.storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)
        payload = {
            "team_id": team_id,
            "created_by_user_id": 700,
            "text": "new q",
            "team_role_id": team_role_id,
            "question_id": "q-new",
            "thread_id": "t-new",
        }
        r1 = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-q-1"},
            json=payload,
        )
        r2 = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-q-1"},
            json=payload,
        )
        self.assertEqual(r1.status_code, 202)
        self.assertEqual(r2.status_code, 202)
        self.assertFalse(r1.json()["idempotent_replay"])
        self.assertTrue(r2.json()["idempotent_replay"])

    def test_post_questions_without_idempotency_key_returns_422(self) -> None:
        client = self._client()
        team_id, _ = self._team_id_and_role_id(client)
        response = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700"},
            json={"team_id": team_id, "created_by_user_id": 700, "text": "x"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "validation.invalid_input")

    def test_get_question_answer_not_ready_returns_409_machine_code(self) -> None:
        client = self._client()
        team_id, role_id = self._team_id_and_role_id(client)
        team_role_id = int(client.app.state.runtime.storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)
        _ = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-q-2"},
            json={
                "team_id": team_id,
                "created_by_user_id": 700,
                "text": "not ready",
                "team_role_id": team_role_id,
                "question_id": "q-not-ready",
                "thread_id": "t-not-ready",
            },
        )
        response = client.get("/api/v1/questions/q-not-ready/answer", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "qa_answer_not_ready")

    def test_get_question_status_question_answer_and_resolve(self) -> None:
        client = self._client()
        s = client.get("/api/v1/questions/q-ready/status", headers={"X-Owner-User-Id": "700"})
        q = client.get("/api/v1/questions/q-ready", headers={"X-Owner-User-Id": "700"})
        a = client.get("/api/v1/answers/a-ready", headers={"X-Owner-User-Id": "700"})
        r = client.get("/api/v1/questions/q-ready/answer", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(s.status_code, 200)
        self.assertEqual(q.status_code, 200)
        self.assertEqual(a.status_code, 200)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(s.json()["status"], "answered")
        self.assertEqual(r.json()["answer_id"], "a-ready")

    def test_cursor_contract_for_journal_thread_feed(self) -> None:
        client = self._client()
        team_id, _ = self._team_id_and_role_id(client)
        journal = client.get(
            f"/api/v1/qa-journal?team_id={team_id}",
            headers={"X-Owner-User-Id": "700"},
        )
        thread = client.get(
            "/api/v1/threads/t-ready",
            headers={"X-Owner-User-Id": "700"},
        )
        feed = client.get(
            f"/api/v1/orchestrator/feed?team_id={team_id}",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(journal.status_code, 200)
        self.assertEqual(thread.status_code, 200)
        self.assertEqual(feed.status_code, 200)
        self.assertEqual(journal.json()["meta"]["limit"], 50)
        self.assertIn("next_cursor", journal.json()["meta"])
        self.assertIn("answer_id", journal.json()["items"][0])
        by_qid = {item["question_id"]: item for item in journal.json()["items"]}
        self.assertEqual(by_qid["q-ready"]["answer_id"], "a-ready")
        self.assertIn("questions", thread.json())
        self.assertIn("answers", thread.json())
        self.assertIn("meta", feed.json())

    def test_cursor_limit_over_max_returns_422(self) -> None:
        client = self._client()
        response = client.get("/api/v1/qa-journal?limit=201", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(response.status_code, 422)

    def test_team_runtime_status_overview_includes_current_question_for_busy_role(self) -> None:
        client = self._client()
        storage = client.app.state.runtime.storage
        team_id, role_id = self._team_id_and_role_id(client)
        team_role_id = int(storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)
        self.assertGreater(team_role_id, 0)

        with storage.transaction(immediate=True):
            q = storage.create_question(
                question_id="q-runtime-overview",
                thread_id="t-runtime-overview",
                team_id=team_id,
                created_by_user_id=700,
                target_team_role_id=team_role_id,
                text="runtime overview current question",
                status="accepted",
            )
            storage.transition_question_status(question_id=q.question_id, status="queued")
            started = storage.start_question_dispatch_attempt(question_id=q.question_id, lease_ttl_sec=120, max_attempts=3)
            self.assertIsNotNone(started)
        acquired, _, _ = storage.try_acquire_team_role_busy(
            team_role_id=team_role_id,
            busy_request_id="overview-busy-1",
            busy_owner_user_id=700,
            busy_origin="qa",
            preview_text="runtime overview current question",
            preview_source="user",
            busy_since="2026-04-15T00:00:00+00:00",
            lease_expires_at="2026-04-15T00:05:00+00:00",
        )
        self.assertTrue(acquired)

        response = client.get(
            f"/api/v1/teams/{team_id}/runtime-status/overview",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        target = next((item for item in payload if int(item["team_role_id"]) == team_role_id), None)
        self.assertIsNotNone(target)
        self.assertEqual(target["status"], "busy")
        self.assertIsNotNone(target["current_question"])
        self.assertEqual(target["current_question"]["question_id"], "q-runtime-overview")
        self.assertEqual(target["current_question"]["source"], "question")

    def test_admin_event_bus_endpoints_crud_and_delivery_actions(self) -> None:
        client = self._client()
        team_id, role_id = self._team_id_and_role_id(client)
        team_role_id = int(client.app.state.runtime.storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)

        upsert = client.put(
            "/api/v1/admin/event-subscriptions",
            headers={"X-Owner-User-Id": "700"},
            json={
                "scope": "team",
                "scope_id": str(team_id),
                "interface_type": "mirror",
                "target_id": "team-mirror",
                "mode": "mirror",
                "is_active": True,
            },
        )
        self.assertEqual(upsert.status_code, 200)
        subscription_id = int(upsert.json()["subscription_id"])

        listed = client.get(
            f"/api/v1/admin/event-subscriptions?scope=team&scope_id={team_id}",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(listed.status_code, 200)
        self.assertTrue(any(int(item["subscription_id"]) == subscription_id for item in listed.json()))

        created = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-admin-events-1"},
            json={
                "team_id": team_id,
                "text": "admin bus smoke",
                "team_role_id": team_role_id,
                "thread_id": "t-admin-events",
                "question_id": "q-admin-events",
            },
        )
        self.assertEqual(created.status_code, 202)

        events = client.get(
            "/api/v1/admin/thread-events?thread_id=t-admin-events",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(events.status_code, 200)
        self.assertGreaterEqual(len(events.json()), 1)
        event_id = str(events.json()[0]["event_id"])
        trace = client.get(
            f"/api/v1/admin/thread-events/trace?event_id={event_id}",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(trace.status_code, 200)
        self.assertEqual(str(trace.json()["event"]["event_id"]), event_id)

        deliveries = client.get(
            f"/api/v1/admin/event-deliveries?event_id={event_id}",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(deliveries.status_code, 200)
        self.assertGreaterEqual(len(deliveries.json()), 1)
        delivery_id = int(deliveries.json()[0]["delivery_id"])

        skipped = client.post(
            f"/api/v1/admin/event-deliveries/{delivery_id}/skip",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(skipped.status_code, 200)
        self.assertEqual(skipped.json()["status"], "skipped")

        retried = client.post(
            f"/api/v1/admin/event-deliveries/{delivery_id}/retry",
            headers={"X-Owner-User-Id": "700"},
            json={"reset_attempt_count": True},
        )
        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["status"], "retry_scheduled")
        self.assertEqual(int(retried.json()["attempt_count"]), 0)
        summary = client.get("/api/v1/admin/event-deliveries/summary", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(summary.status_code, 200)
        self.assertIn("failed_dlq", summary.json())

        with client.app.state.runtime.storage.transaction(immediate=True):
            _ = client.app.state.runtime.storage.mark_event_delivery_dlq(
                delivery_id,
                error_code="test",
                error_message="force_dlq",
            )
        dlq_requeue = client.post(
            f"/api/v1/admin/event-deliveries/{delivery_id}/dlq-requeue",
            headers={"X-Owner-User-Id": "700"},
            json={"reset_attempt_count": True},
        )
        self.assertEqual(dlq_requeue.status_code, 200)
        self.assertEqual(dlq_requeue.json()["status"], "retry_scheduled")

        deleted = client.delete(
            f"/api/v1/admin/event-subscriptions/{subscription_id}",
            headers={"X-Owner-User-Id": "700"},
        )
        self.assertEqual(deleted.status_code, 204)

    def test_admin_recovery_reset_dry_run_keeps_state(self) -> None:
        client = self._client()
        storage = client.app.state.runtime.storage
        team_id, role_id = self._team_id_and_role_id(client)
        team_role_id = int(storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)
        self.assertGreater(team_role_id, 0)

        with storage.transaction(immediate=True):
            q = storage.create_question(
                question_id="q-recovery-dry",
                thread_id="t-recovery-dry",
                team_id=team_id,
                created_by_user_id=700,
                target_team_role_id=team_role_id,
                text="recovery dry run",
                status="accepted",
            )
            storage.transition_question_status(question_id=q.question_id, status="queued")
            storage.start_question_dispatch_attempt(question_id=q.question_id, lease_ttl_sec=120, max_attempts=3)
            acquired, _, _ = storage.try_acquire_team_role_busy(
                team_role_id=team_role_id,
                busy_request_id="dry-busy-1",
                busy_owner_user_id=700,
                busy_origin="qa",
                preview_text="busy",
                preview_source="user",
                busy_since="2026-04-15T00:00:00+00:00",
                lease_expires_at="2026-04-15T00:05:00+00:00",
            )
            self.assertTrue(acquired)
            ev = storage.create_thread_event(
                team_id=team_id,
                thread_id="t-recovery-dry",
                event_type="thread.message.created",
                author_type="user",
                direction="question",
                origin_interface="telegram",
                source_ref_type="question",
                source_ref_id=q.question_id,
                question_id=q.question_id,
            )
            delivery = storage.enqueue_event_delivery(
                event_id=ev.event_id,
                interface_type="mirror",
                target_id="dry-target",
            )
            _ = storage.mark_event_delivery_retry(
                int(delivery.delivery_id),
                error_code="tmp",
                error_message="tmp",
                retry_delay_sec=0,
            )

        response = client.post(
            "/api/v1/admin/recovery/queues/reset",
            headers={"X-Owner-User-Id": "700"},
            json={"scope": {"mode": "global"}, "dry_run": True},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["applied"])
        self.assertTrue(body["dry_run"])
        self.assertGreaterEqual(int(body["before"]["questions_in_progress"]), 1)
        self.assertEqual(body["before"], body["after"])

        q_after = storage.get_question("q-recovery-dry")
        self.assertEqual((q_after.status if q_after else None), "in_progress")

    def test_admin_recovery_reset_apply_resets_runtime_qa_and_event_deliveries(self) -> None:
        client = self._client()
        storage = client.app.state.runtime.storage
        team_id, role_id = self._team_id_and_role_id(client)
        team_role_id = int(storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)
        self.assertGreater(team_role_id, 0)

        with storage.transaction(immediate=True):
            q = storage.create_question(
                question_id="q-recovery-apply",
                thread_id="t-recovery-apply",
                team_id=team_id,
                created_by_user_id=700,
                target_team_role_id=team_role_id,
                text="recovery apply",
                status="accepted",
            )
            storage.transition_question_status(question_id=q.question_id, status="queued")
            started = storage.start_question_dispatch_attempt(question_id=q.question_id, lease_ttl_sec=120, max_attempts=3)
            self.assertIsNotNone(started)
            acquired, _, _ = storage.try_acquire_team_role_busy(
                team_role_id=team_role_id,
                busy_request_id="apply-busy-1",
                busy_owner_user_id=700,
                busy_origin="qa",
                preview_text="busy",
                preview_source="user",
                busy_since="2026-04-15T00:00:00+00:00",
                lease_expires_at="2026-04-15T00:05:00+00:00",
            )
            self.assertTrue(acquired)
            ev = storage.create_thread_event(
                team_id=team_id,
                thread_id="t-recovery-apply",
                event_type="thread.message.created",
                author_type="user",
                direction="question",
                origin_interface="telegram",
                source_ref_type="question",
                source_ref_id=q.question_id,
                question_id=q.question_id,
            )
            d_pending = storage.enqueue_event_delivery(
                event_id=ev.event_id,
                interface_type="mirror",
                target_id="pending-target",
            )
            d_retry = storage.enqueue_event_delivery(
                event_id=ev.event_id,
                interface_type="mirror",
                target_id="retry-target",
            )
            d_progress = storage.enqueue_event_delivery(
                event_id=ev.event_id,
                interface_type="mirror",
                target_id="progress-target",
            )
            _ = storage.mark_event_delivery_retry(
                int(d_retry.delivery_id),
                error_code="tmp",
                error_message="tmp",
                retry_delay_sec=0,
            )
            claimed = storage.claim_pending_event_deliveries(limit=10, lease_owner="worker-1", lease_ttl_sec=120)
            claimed_ids = {int(item.delivery_id) for item in claimed}
            self.assertIn(int(d_progress.delivery_id), claimed_ids)

        response = client.post(
            "/api/v1/admin/recovery/queues/reset",
            headers={"X-Owner-User-Id": "700"},
            json={"scope": {"mode": "global"}, "dry_run": False},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["applied"])
        self.assertFalse(body["dry_run"])
        self.assertGreaterEqual(int(body["before"]["questions_in_progress"]), 1)
        self.assertEqual(int(body["after"]["questions_in_progress"]), 0)
        self.assertEqual(int(body["after"]["runtime_status_busy"]), 0)

        q_after = storage.get_question("q-recovery-apply")
        self.assertEqual((q_after.status if q_after else None), "accepted")
        status_after = storage.get_team_role_runtime_status(team_role_id)
        self.assertEqual((status_after.status if status_after else None), "free")
        self.assertEqual((status_after.busy_request_id if status_after else None), None)

        deliveries = storage.list_event_deliveries(event_id=ev.event_id, limit=50)
        statuses = {str(item.status) for item in deliveries}
        self.assertEqual(statuses, {"retry_scheduled"})
        self.assertTrue(all(int(item.attempt_count) == 0 for item in deliveries))

    def test_stage5_endpoints_owner_authz_401_403(self) -> None:
        client = self._client()
        endpoints = (
            ("GET", "/api/v1/questions/q-ready/status", None),
            ("GET", "/api/v1/questions/q-ready", None),
            ("GET", "/api/v1/answers/a-ready", None),
            ("GET", "/api/v1/questions/q-ready/answer", None),
            ("GET", "/api/v1/qa-journal", None),
            ("GET", "/api/v1/threads/t-ready", None),
            ("GET", "/api/v1/orchestrator/feed?team_id=1", None),
            (
                "POST",
                "/api/v1/questions",
                {"team_id": 1, "created_by_user_id": 1, "text": "x"},
            ),
        )
        for method, path, body in endpoints:
            response = client.request(method, path, json=body)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"]["code"], "auth.unauthorized")
            headers = {"X-Owner-User-Id": "701"}
            if method == "POST":
                headers["Idempotency-Key"] = "idem-authz"
            response = client.request(method, path, headers=headers, json=body)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], "auth.unauthorized")

    def test_stage5_not_found_mapping_404(self) -> None:
        client = self._client()
        checks = (
            ("GET", "/api/v1/questions/q-missing/status"),
            ("GET", "/api/v1/questions/q-missing"),
            ("GET", "/api/v1/answers/a-missing"),
            ("GET", "/api/v1/questions/q-missing/answer"),
        )
        for method, path in checks:
            response = client.request(method, path, headers={"X-Owner-User-Id": "700"})
            self.assertEqual(response.status_code, 404)
            self.assertIn(response.json()["error"]["code"], {"qa_not_found", "storage.not_found"})

    def test_stage5_validation_mapping_422(self) -> None:
        client = self._client()
        team_id, role_id = self._team_id_and_role_id(client)
        team_role_id = int(client.app.state.runtime.storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)

        r_mismatch = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-q-3"},
            json={
                "team_id": team_id,
                "created_by_user_id": 700,
                "text": "first",
                "team_role_id": team_role_id,
                "question_id": "q-mismatch",
                "thread_id": "t-mismatch",
            },
        )
        self.assertEqual(r_mismatch.status_code, 202)
        r_mismatch_2 = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-q-3"},
            json={
                "team_id": team_id,
                "created_by_user_id": 700,
                "text": "second",
                "team_role_id": team_role_id,
                "question_id": "q-mismatch",
                "thread_id": "t-mismatch",
            },
        )
        self.assertEqual(r_mismatch_2.status_code, 422)
        self.assertEqual(r_mismatch_2.json()["error"]["code"], "qa_idempotency_mismatch")

        r_cursor = client.get("/api/v1/qa-journal?cursor=bad-cursor", headers={"X-Owner-User-Id": "700"})
        self.assertEqual(r_cursor.status_code, 422)
        self.assertEqual(r_cursor.json()["error"]["code"], "validation.invalid_input")

    def test_post_questions_requires_team_id_and_no_legacy_alias(self) -> None:
        client = self._client()
        response_missing_team = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-missing-team"},
            json={"created_by_user_id": 700, "text": "hello @dev"},
        )
        self.assertEqual(response_missing_team.status_code, 422)

        response_legacy_alias = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-legacy-alias"},
            json={
                "team_id": 1,
                "created_by_user_id": 700,
                "text": "hello @dev",
                "target_team_role_id": 1,
            },
        )
        self.assertEqual(response_legacy_alias.status_code, 422)

    def test_post_questions_routing_by_tags_and_validation_errors(self) -> None:
        client = self._client()
        team_id, _ = self._team_id_and_role_id(client)

        ok = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-tag-ok"},
            json={
                "team_id": team_id,
                "created_by_user_id": 700,
                "text": "please answer @dev",
                "question_id": "q-tag-ok",
                "thread_id": "t-tag-ok",
            },
        )
        self.assertEqual(ok.status_code, 202)

        no_tag = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-tag-none"},
            json={
                "team_id": team_id,
                "created_by_user_id": 700,
                "text": "no mentions here",
                "question_id": "q-tag-none",
                "thread_id": "t-tag-none",
            },
        )
        self.assertEqual(no_tag.status_code, 422)
        self.assertEqual(no_tag.json()["error"]["code"], "qa_orchestrator_not_configured")

        with client.app.state.runtime.storage.transaction(immediate=True):
            role2 = client.app.state.runtime.storage.upsert_role(
                role_name="ops",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            client.app.state.runtime.storage.bind_master_role_to_team(team_id, role2.role_id)

        multi_tag = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-tag-multi"},
            json={
                "team_id": team_id,
                "created_by_user_id": 700,
                "text": "route @dev and @ops",
                "question_id": "q-tag-multi",
                "thread_id": "t-tag-multi",
            },
        )
        self.assertEqual(multi_tag.status_code, 422)
        self.assertEqual(multi_tag.json()["error"]["code"], "qa_lineage_invalid")

    def test_post_questions_no_tag_uses_single_orchestrator_fallback(self) -> None:
        client = self._client()
        team_id, role_id = self._team_id_and_role_id(client)
        with client.app.state.runtime.storage.transaction(immediate=True):
            client.app.state.runtime.storage.set_team_role_mode(team_id, role_id, "orchestrator")

        response = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-orch-fallback"},
            json={
                "team_id": team_id,
                "created_by_user_id": 700,
                "text": "no mentions here",
                "question_id": "q-orch-fallback",
                "thread_id": "t-orch-fallback",
            },
        )
        self.assertEqual(response.status_code, 202)
        team_role_id = int(client.app.state.runtime.storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)
        self.assertEqual(response.json()["question"]["team_role_id"], team_role_id)

    def test_post_questions_no_tag_with_ambiguous_orchestrator_returns_422(self) -> None:
        client = self._client()
        team_id, _ = self._team_id_and_role_id(client)
        with client.app.state.runtime.storage.transaction(immediate=True):
            role2 = client.app.state.runtime.storage.upsert_role(
                role_name="ops",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            client.app.state.runtime.storage.bind_master_role_to_team(team_id, role2.role_id)
            # Intentional white-box setup to model corrupted state with >1 active orchestrator.
            client.app.state.runtime.storage._conn.execute(  # noqa: SLF001
                "UPDATE team_roles SET mode = 'orchestrator', enabled = 1, is_active = 1 WHERE team_id = ?",
                (team_id,),
            )

        response = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-orch-amb"},
            json={
                "team_id": team_id,
                "created_by_user_id": 700,
                "text": "still no tags",
                "question_id": "q-orch-amb",
                "thread_id": "t-orch-amb",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "qa_orchestrator_ambiguous")

    def test_post_questions_explicit_team_role_priority_and_mapping(self) -> None:
        client = self._client()
        team_id, role_id = self._team_id_and_role_id(client)
        team_role_id = int(client.app.state.runtime.storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)

        explicit_wins = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-explicit-priority"},
            json={
                "team_id": team_id,
                "created_by_user_id": 700,
                "text": "text has @unknown, explicit role should win",
                "team_role_id": team_role_id,
                "question_id": "q-explicit-priority",
                "thread_id": "t-explicit-priority",
            },
        )
        self.assertEqual(explicit_wins.status_code, 202)
        self.assertEqual(explicit_wins.json()["question"]["team_role_id"], team_role_id)

        with client.app.state.runtime.storage.transaction(immediate=True):
            other_group = client.app.state.runtime.storage.upsert_group(-9782, "g2")
            other_role = client.app.state.runtime.storage.upsert_role(
                role_name="ops2",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            client.app.state.runtime.storage.ensure_group_role(other_group.group_id, other_role.role_id)
            other_team_id = int(other_group.team_id or 0)
            other_team_role_id = int(
                client.app.state.runtime.storage.resolve_team_role_id(other_team_id, other_role.role_id, ensure_exists=True) or 0
            )

        mismatch = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-explicit-mismatch"},
            json={
                "team_id": team_id,
                "created_by_user_id": 700,
                "text": "explicit mismatch",
                "team_role_id": other_team_role_id,
                "question_id": "q-explicit-mismatch",
                "thread_id": "t-explicit-mismatch",
            },
        )
        self.assertEqual(mismatch.status_code, 422)
        self.assertEqual(mismatch.json()["error"]["code"], "qa_lineage_invalid")

    def test_post_questions_not_found_mapping_404_qa_not_found(self) -> None:
        client = self._client()
        not_found_team = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-nf-team"},
            json={
                "team_id": 999999,
                "created_by_user_id": 700,
                "text": "x",
                "team_role_id": 1,
                "question_id": "q-nf-team",
                "thread_id": "t-nf-team",
            },
        )
        self.assertEqual(not_found_team.status_code, 404)
        self.assertEqual(not_found_team.json()["error"]["code"], "qa_not_found")

        team_id, _ = self._team_id_and_role_id(client)
        not_found_role = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-nf-role"},
            json={
                "team_id": team_id,
                "created_by_user_id": 700,
                "text": "x",
                "team_role_id": 999999,
                "question_id": "q-nf-role",
                "thread_id": "t-nf-role",
            },
        )
        self.assertEqual(not_found_role.status_code, 404)
        self.assertEqual(not_found_role.json()["error"]["code"], "qa_not_found")

    def test_post_questions_requires_working_and_root_dirs_for_fs_skills(self) -> None:
        client = self._client()
        team_id, role_id = self._team_id_and_role_id(client)
        team_role_id = int(client.app.state.runtime.storage.resolve_team_role_id(team_id, role_id, ensure_exists=True) or 0)
        with client.app.state.runtime.storage.transaction(immediate=True):
            client.app.state.runtime.storage.upsert_role_skill_for_team_role(team_role_id, "fs.read_file", enabled=True, config={})

        missing = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-fs-missing"},
            json={
                "team_id": team_id,
                "created_by_user_id": 700,
                "text": "fs question",
                "team_role_id": team_role_id,
                "question_id": "q-fs-missing",
                "thread_id": "t-fs-missing",
            },
        )
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(missing.json()["error"]["code"], "validation.invalid_input")
        self.assertEqual(
            missing.json()["error"].get("details", {}).get("missing_fields"),
            ["root_dir"],
        )

        with client.app.state.runtime.storage.transaction(immediate=True):
            client.app.state.runtime.storage.set_team_role_working_dir_by_id(team_role_id, "/abs/work")
            client.app.state.runtime.storage.set_team_role_root_dir_by_id(team_role_id, "/abs/root")
        ok = client.post(
            "/api/v1/questions",
            headers={"X-Owner-User-Id": "700", "Idempotency-Key": "idem-fs-ok"},
            json={
                "team_id": team_id,
                "created_by_user_id": 700,
                "text": "fs question",
                "team_role_id": team_role_id,
                "question_id": "q-fs-ok",
                "thread_id": "t-fs-ok",
            },
        )
        self.assertEqual(ok.status_code, 202)


if __name__ == "__main__":
    unittest.main()
