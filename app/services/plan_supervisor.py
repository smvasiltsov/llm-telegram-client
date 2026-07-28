from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from app.models import PlanRun, PlanStep
from app.storage import Storage

PLAN_STEP_STATUSES = {
    "pending",
    "in_progress",
    "reported",
    "approval_requested",
    "approved",
    "rejected",
    "done",
    "blocked",
}

PLAN_RUN_STATUSES = {"active", "completed", "failed", "cancelled"}

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"in_progress"},
    "in_progress": {"reported", "blocked"},
    "reported": {"approval_requested"},
    "approval_requested": {"approved", "rejected"},
    "approved": {"done"},
    "rejected": {"in_progress"},
    "blocked": {"in_progress"},
    "done": set(),
}


@dataclass(frozen=True)
class PlanStepInput:
    step_id: str
    title: str
    description: str | None = None


class PlanSupervisorValidationError(ValueError):
    pass


class PlanSupervisorService:
    def __init__(self, storage: Storage, *, emit_thread_events: bool = True) -> None:
        self._storage = storage
        self._emit_events = bool(emit_thread_events)

    def start_plan(
        self,
        *,
        team_id: int,
        thread_id: str,
        goal: str,
        steps: list[PlanStepInput],
        actor_role: str | None,
        created_by_user_id: int | None,
        require_manual_approval: bool = True,
    ) -> dict[str, object]:
        if not steps:
            raise PlanSupervisorValidationError("Plan must contain at least one step")
        seen_ids: set[str] = set()
        normalized: list[PlanStepInput] = []
        for raw in steps:
            sid = str(raw.step_id).strip()
            title = str(raw.title).strip()
            if not sid:
                raise PlanSupervisorValidationError("step_id is required")
            if sid in seen_ids:
                raise PlanSupervisorValidationError(f"Duplicate step_id: {sid}")
            if not title:
                raise PlanSupervisorValidationError(f"title is required for step_id={sid}")
            seen_ids.add(sid)
            normalized.append(PlanStepInput(step_id=sid, title=title, description=raw.description))

        plan_run_id = f"plan_{secrets.token_hex(8)}"
        with self._storage.transaction(immediate=True):
            run = self._storage.create_plan_run(
                plan_run_id=plan_run_id,
                team_id=int(team_id),
                thread_id=str(thread_id),
                goal=str(goal),
                total_steps=len(normalized),
                created_by_user_id=created_by_user_id,
                actor_role=actor_role,
                require_manual_approval=require_manual_approval,
            )
            self._storage.create_plan_steps(
                plan_run_id,
                [(item.step_id, idx + 1, item.title, item.description) for idx, item in enumerate(normalized)],
            )
            first = self._apply_transition(
                plan_run_id=plan_run_id,
                step_id=normalized[0].step_id,
                to_status="in_progress",
                event_type="step_started",
                actor_id=actor_role or "system",
                payload={"goal": goal},
            )
            self._storage.set_plan_run_current_step(plan_run_id, step_id=first.step_id, step_order=first.step_order)
            self._emit_thread_event(run=run, event_type="plan.started", step=first, payload={"goal": goal})
        return self.get_plan_ui_projection(plan_run_id)

    def report_step(
        self,
        *,
        plan_run_id: str,
        step_id: str,
        summary: str,
        artifacts: list[dict[str, object]] | None = None,
        test_commands: list[str] | None = None,
        result: str = "done",
        actor_id: str | None = None,
    ) -> dict[str, object]:
        to_status = "reported" if result == "done" else "blocked"
        payload = {
            "summary": summary,
            "artifacts": artifacts or [],
            "test_commands": test_commands or [],
            "result": result,
        }
        with self._storage.transaction(immediate=True):
            updated = self._apply_transition(
                plan_run_id=plan_run_id,
                step_id=step_id,
                to_status=to_status,
                event_type="step_reported",
                actor_id=actor_id,
                payload=payload,
                summary=summary,
                artifacts_json=json.dumps(artifacts or [], ensure_ascii=False),
                test_commands_json=json.dumps(test_commands or [], ensure_ascii=False),
            )
            if to_status == "blocked":
                self._storage.update_plan_run_status(plan_run_id, status="failed", failed_step_id=step_id)
        return self.get_plan_ui_projection(plan_run_id)

    def request_approval(self, *, plan_run_id: str, step_id: str, note: str | None = None) -> dict[str, object]:
        with self._storage.transaction(immediate=True):
            self._apply_transition(
                plan_run_id=plan_run_id,
                step_id=step_id,
                to_status="approval_requested",
                event_type="approval_requested",
                payload={"note": note or ""},
            )
        return self.get_plan_ui_projection(plan_run_id)

    def approve_next(self, *, plan_run_id: str, step_id: str, actor_id: str | None = None, comment: str | None = None) -> dict[str, object]:
        with self._storage.transaction(immediate=True):
            self._apply_transition(plan_run_id=plan_run_id, step_id=step_id, to_status="approved", event_type="step_approved", actor_id=actor_id, payload={"comment": comment or ""})
            done_step = self._apply_transition(plan_run_id=plan_run_id, step_id=step_id, to_status="done", event_type="step_done", actor_id=actor_id)
            run = self._require_plan_run(plan_run_id)
            steps = self._storage.list_plan_steps(plan_run_id)
            next_step = self._find_next_step(steps, done_step.step_order)
            if next_step is None:
                self._storage.set_plan_run_current_step(plan_run_id, step_id=None, step_order=None)
                self._storage.update_plan_run_status(plan_run_id, status="completed")
            else:
                issued = self._apply_transition(plan_run_id=plan_run_id, step_id=next_step.step_id, to_status="in_progress", event_type="step_started", actor_id="system")
                self._storage.set_plan_run_current_step(plan_run_id, step_id=issued.step_id, step_order=issued.step_order)
            self._refresh_completed_counter(plan_run_id)
            self._emit_thread_event(run=run, event_type="plan.step_approved", step=done_step, payload={"comment": comment or ""})
        return self.get_plan_ui_projection(plan_run_id)

    def reject_step(self, *, plan_run_id: str, step_id: str, actor_id: str | None = None, comment: str | None = None) -> dict[str, object]:
        with self._storage.transaction(immediate=True):
            self._apply_transition(plan_run_id=plan_run_id, step_id=step_id, to_status="rejected", event_type="step_rejected", actor_id=actor_id, payload={"comment": comment or ""})
            rework = self._apply_transition(plan_run_id=plan_run_id, step_id=step_id, to_status="in_progress", event_type="step_rework_started", actor_id="system")
            self._storage.set_plan_run_current_step(plan_run_id, step_id=rework.step_id, step_order=rework.step_order)
            run = self._require_plan_run(plan_run_id)
            self._emit_thread_event(run=run, event_type="plan.step_rejected", step=rework, payload={"comment": comment or ""})
        return self.get_plan_ui_projection(plan_run_id)

    def get_plan_run_view(self, plan_run_id: str) -> dict[str, object]:
        run = self._require_plan_run(plan_run_id)
        steps = self._storage.list_plan_steps(plan_run_id)
        events = self._storage.list_plan_events(plan_run_id, limit=200)
        return {
            "plan_run": {
                "plan_run_id": run.plan_run_id,
                "team_id": run.team_id,
                "thread_id": run.thread_id,
                "goal": run.goal,
                "status": run.status,
                "current_step_id": run.current_step_id,
                "current_step_order": run.current_step_order,
                "total_steps": run.total_steps,
                "completed_steps": sum(1 for s in steps if s.status == "done"),
                "created_at": run.created_at,
                "updated_at": run.updated_at,
            },
            "steps": [
                {
                    "step_id": s.step_id,
                    "order": s.step_order,
                    "title": s.title,
                    "description": s.description,
                    "status": s.status,
                    "summary": s.summary,
                    "artifacts": self._json_loads(s.artifacts_json, default=[]),
                    "test_commands": self._json_loads(s.test_commands_json, default=[]),
                    "started_at": s.started_at,
                    "reported_at": s.reported_at,
                    "approved_at": s.approved_at,
                    "done_at": s.done_at,
                }
                for s in steps
            ],
            "events": [
                {
                    "event_id": e.event_id,
                    "step_id": e.step_id,
                    "event_type": e.event_type,
                    "from_status": e.from_status,
                    "to_status": e.to_status,
                    "actor_type": e.actor_type,
                    "actor_id": e.actor_id,
                    "payload": self._json_loads(e.payload_json, default={}),
                    "created_at": e.created_at,
                }
                for e in events
            ],
        }

    def get_plan_ui_projection(self, plan_run_id: str) -> dict[str, object]:
        view = self.get_plan_run_view(plan_run_id)
        steps = list(view.get("steps") or [])
        total = len(steps)
        done = sum(1 for item in steps if str(item.get("status")) == "done")
        view["ui"] = {
            "progress_total": total,
            "progress_done": done,
            "progress_percent": int((done * 100) / total) if total else 0,
            "current_step_id": (view.get("plan_run") or {}).get("current_step_id"),
        }
        return view

    def _apply_transition(
        self,
        *,
        plan_run_id: str,
        step_id: str,
        to_status: str,
        event_type: str,
        actor_id: str | None = None,
        payload: dict[str, object] | None = None,
        summary: str | None = None,
        artifacts_json: str | None = None,
        test_commands_json: str | None = None,
    ) -> PlanStep:
        previous = self._require_transition(plan_run_id=plan_run_id, step_id=step_id, to_status=to_status)
        updated = self._storage.set_plan_step_status(
            plan_run_id,
            step_id,
            to_status=to_status,
            summary=summary,
            artifacts_json=artifacts_json,
            test_commands_json=test_commands_json,
        )
        self._storage.create_plan_event(
            plan_run_id=plan_run_id,
            step_id=step_id,
            event_type=event_type,
            from_status=previous.status,
            to_status=to_status,
            actor_type="supervisor",
            actor_id=actor_id,
            payload_json=json.dumps(payload or {}, ensure_ascii=False),
        )
        run = self._require_plan_run(plan_run_id)
        self._emit_thread_event(run=run, event_type=f"plan.transition.{event_type}", step=updated, payload=payload)
        return updated

    def _require_transition(self, *, plan_run_id: str, step_id: str, to_status: str) -> PlanStep:
        if to_status not in PLAN_STEP_STATUSES:
            raise PlanSupervisorValidationError(f"Unknown status: {to_status}")
        step = self._storage.get_plan_step(plan_run_id, step_id)
        if step is None:
            raise PlanSupervisorValidationError(f"Step not found: {step_id}")
        allowed = _ALLOWED_TRANSITIONS.get(step.status, set())
        if to_status not in allowed:
            raise PlanSupervisorValidationError(f"Invalid transition: {step.status} -> {to_status}")
        return step

    def _require_plan_run(self, plan_run_id: str) -> PlanRun:
        run = self._storage.get_plan_run(plan_run_id)
        if run is None:
            raise PlanSupervisorValidationError(f"Plan run not found: {plan_run_id}")
        if run.status not in PLAN_RUN_STATUSES:
            raise PlanSupervisorValidationError(f"Unknown plan status: {run.status}")
        return run

    @staticmethod
    def _find_next_step(steps: list[PlanStep], current_order: int) -> PlanStep | None:
        for step in steps:
            if int(step.step_order) > int(current_order):
                return step
        return None

    def _refresh_completed_counter(self, plan_run_id: str) -> None:
        self._storage._require_write_transaction("_refresh_completed_counter")
        steps = self._storage.list_plan_steps(plan_run_id)
        done = sum(1 for item in steps if item.status == "done")
        now = datetime.now(timezone.utc).isoformat()
        cur = self._storage._conn.cursor()
        cur.execute(
            "UPDATE plan_runs SET completed_steps = ?, updated_at = ? WHERE plan_run_id = ?",
            (done, now, str(plan_run_id)),
        )

    def _emit_thread_event(
        self,
        *,
        run: PlanRun,
        event_type: str,
        step: PlanStep | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        if not self._emit_events:
            return
        body = {
            "plan_run_id": run.plan_run_id,
            "plan_status": run.status,
            "step_id": step.step_id if step is not None else None,
            "step_status": step.status if step is not None else None,
            "payload": payload or {},
        }
        self._storage.create_thread_event(
            team_id=run.team_id,
            thread_id=run.thread_id,
            event_type=event_type,
            author_type="system",
            direction="system_to_ui",
            origin_interface="api",
            payload_json=json.dumps(body, ensure_ascii=False),
        )

    @staticmethod
    def _json_loads(raw: str | None, *, default: object) -> object:
        if not raw:
            return default
        try:
            return json.loads(raw)
        except Exception:
            return default
