from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.plan_supervisor import PlanStepInput, PlanSupervisorService
from app.storage import Storage
from skills_sdk.contract import SkillContext, SkillResult, SkillSpec

SKILL_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SKILL_DIR / "config.json"
SUPPORTED_OPERATIONS = {
    "start_plan",
    "report_step",
}


class PlanSupervisorSkill:
    def describe(self) -> SkillSpec:
        return SkillSpec(
            skill_id="plan_supervisor",
            name="Plan Supervisor",
            version="0.1.0",
            description=(
                "Planner protocol for autonomous step execution. Use ONLY two operations: start_plan and report_step. "
                "start_plan starts a new plan from scratch and does NOT require step_id or plan_run_id. "
                "Required payload for start_plan: goal (string), steps (non-empty array of {step_id, title, optional description}). "
                "report_step reports completion of the CURRENT step. Required payload for report_step: plan_run_id (string), step_id (string), summary (string). "
                "Optional for report_step: artifacts (array), test_commands (array of strings), result ('done' or 'blocked', default 'done'). "
                "Runtime injects team_id/thread_id automatically; do not invent them. "
                "After start_plan, always use returned plan_run_id for next report_step."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": [
                            "start_plan",
                            "report_step",
                        ],
                    },
                    "command": {"type": "string"},
                    "payload": {"type": "object"},
                    "team_id": {"type": "integer"},
                    "thread_id": {"type": "string"},
                },
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "operation": {"const": "start_plan"},
                            "payload": {
                                "type": "object",
                                "properties": {
                                    "goal": {"type": "string", "minLength": 1},
                                    "steps": {
                                        "type": "array",
                                        "minItems": 1,
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "step_id": {"type": "string", "minLength": 1},
                                                "title": {"type": "string", "minLength": 1},
                                                "description": {"type": "string"},
                                            },
                                            "required": ["step_id", "title"],
                                        },
                                    },
                                },
                                "required": ["goal", "steps"],
                            },
                        },
                        "required": ["operation", "payload"],
                    },
                    {
                        "type": "object",
                        "properties": {
                            "operation": {"const": "report_step"},
                            "payload": {
                                "type": "object",
                                "properties": {
                                    "plan_run_id": {"type": "string", "minLength": 1},
                                    "step_id": {"type": "string", "minLength": 1},
                                    "summary": {"type": "string", "minLength": 1},
                                    "result": {"type": "string", "enum": ["done", "blocked"]},
                                    "artifacts": {"type": "array"},
                                    "test_commands": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["plan_run_id", "step_id", "summary"],
                            },
                        },
                        "required": ["operation", "payload"],
                    },
                    {
                        "type": "object",
                        "properties": {
                            "command": {"const": "start_plan"},
                            "payload": {
                                "type": "object",
                                "properties": {
                                    "goal": {"type": "string", "minLength": 1},
                                    "steps": {
                                        "type": "array",
                                        "minItems": 1,
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "step_id": {"type": "string", "minLength": 1},
                                                "title": {"type": "string", "minLength": 1},
                                                "description": {"type": "string"},
                                            },
                                            "required": ["step_id", "title"],
                                        },
                                    },
                                },
                                "required": ["goal", "steps"],
                            },
                        },
                        "required": ["command", "payload"],
                    },
                    {
                        "type": "object",
                        "properties": {
                            "command": {"const": "report_step"},
                            "payload": {
                                "type": "object",
                                "properties": {
                                    "plan_run_id": {"type": "string", "minLength": 1},
                                    "step_id": {"type": "string", "minLength": 1},
                                    "summary": {"type": "string", "minLength": 1},
                                    "result": {"type": "string", "enum": ["done", "blocked"]},
                                    "artifacts": {"type": "array"},
                                    "test_commands": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["plan_run_id", "step_id", "summary"],
                            },
                        },
                        "required": ["command", "payload"],
                    },
                ],
                "additionalProperties": True,
            },
            mode="read_write",
            timeout_sec=30,
        )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        resolved = self._load_merged_config(config)
        errors: list[str] = []
        emit_events = resolved.get("emit_thread_events", True)
        if not isinstance(emit_events, bool):
            errors.append("config.emit_thread_events must be boolean")
        for key in ("directive_start_template", "directive_next_template", "directive_done_template"):
            value = resolved.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"config.{key} must be non-empty string")
        database_path = resolved.get("database_path")
        if not isinstance(database_path, str) or not str(database_path).strip():
            errors.append("config.database_path must be non-empty string")
        return errors

    def run(self, ctx: SkillContext, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        resolved_config = self._load_merged_config(config)
        config_errors = self.validate_config(resolved_config)
        if config_errors:
            return SkillResult(ok=False, error="invalid_config", output={"errors": config_errors})

        try:
            operation = self._resolve_operation(arguments)
            payload = arguments.get("payload")
            if payload is None:
                payload = {}
            if not isinstance(payload, dict):
                raise ValueError("Field 'payload' must be object")
            operation = self._normalize_operation(operation=operation, payload=payload)

            team_id = self._resolve_team_id(
                arguments=arguments,
                payload=payload,
            )
            thread_id = self._resolve_thread_id(
                arguments=arguments,
                payload=payload,
            )
            emit_thread_events = bool(resolved_config.get("emit_thread_events", True))
            db_path = str(resolved_config.get("database_path", "")).strip()

            storage = Storage(db_path)
            service = PlanSupervisorService(storage, emit_thread_events=emit_thread_events)
            if operation == "start_plan":
                goal = str(payload.get("goal", "")).strip()
                if not goal:
                    raise ValueError("payload.goal is required")
                raw_steps = payload.get("steps")
                if not isinstance(raw_steps, list) or not raw_steps:
                    raise ValueError("payload.steps must be non-empty list")
                steps: list[PlanStepInput] = []
                for idx, item in enumerate(raw_steps):
                    if not isinstance(item, dict):
                        raise ValueError(f"payload.steps[{idx}] must be object")
                    steps.append(
                        PlanStepInput(
                            step_id=str(item.get("step_id", "")).strip(),
                            title=str(item.get("title", "")).strip(),
                            description=str(item.get("description")) if item.get("description") is not None else None,
                        )
                    )
                result = service.start_plan(
                    team_id=team_id,
                    thread_id=thread_id,
                    goal=goal,
                    steps=steps,
                    actor_role=str(ctx.role_name or "agent"),
                    created_by_user_id=int(ctx.user_id),
                    require_manual_approval=bool(payload.get("require_manual_approval", True)),
                )
                directive = self._build_directive(
                    template=str(resolved_config.get("directive_start_template")),
                    result=result,
                )
                llm_message_text = self._build_llm_message_for_start_plan(goal=goal, raw_steps=raw_steps)
            else:
                plan_run_id = self._require_text(arguments.get("plan_run_id") or payload.get("plan_run_id"), "plan_run_id")
                step_id = self._require_text(payload.get("step_id"), "payload.step_id")
                summary_text = self._require_text(payload.get("summary"), "payload.summary")
                report_result = service.report_step(
                    plan_run_id=plan_run_id,
                    step_id=step_id,
                    summary=summary_text,
                    artifacts=payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else [],
                    test_commands=[str(x) for x in (payload.get("test_commands") or [])] if isinstance(payload.get("test_commands"), list) else [],
                    result=str(payload.get("result") or "done").strip().lower(),
                    actor_id=str(ctx.user_id),
                )
                step = self._find_step(report_result, step_id)
                if step is not None and str(step.get("status")) == "reported":
                    service.request_approval(plan_run_id=plan_run_id, step_id=step_id, note="auto")
                    result = service.approve_next(plan_run_id=plan_run_id, step_id=step_id, actor_id=str(ctx.user_id), comment="auto")
                else:
                    result = report_result
                directive_template = str(resolved_config.get("directive_done_template"))
                if self._has_next_step(result):
                    directive_template = str(resolved_config.get("directive_next_template"))
                directive = self._build_directive(template=directive_template, result=result)
                llm_message_text = self._build_llm_message_for_report_step(step_id=step_id, summary=summary_text)

            outbox_projection = self._build_outbox_projection(
                storage=storage,
                team_id=team_id,
                thread_id=thread_id,
            )
            if emit_thread_events and directive:
                self._emit_llm_mcp_dialogue_turn(
                    storage=storage,
                    team_id=team_id,
                    thread_id=thread_id,
                    role_id=int(ctx.role_id),
                    llm_text=llm_message_text,
                    directive_text=directive,
                )
                outbox_projection = self._build_outbox_projection(
                    storage=storage,
                    team_id=team_id,
                    thread_id=thread_id,
                )
            if emit_thread_events and not outbox_projection["events"]:
                return SkillResult(
                    ok=False,
                    error="thread_event_not_published",
                    output={"type": "plan_supervisor_result", "operation": operation},
                )

            return SkillResult(
                ok=True,
                output={
                    "type": "plan_supervisor_result",
                    "operation": operation,
                    "result": result,
                    "directive": directive,
                    "ui_projection": {
                        "plan_run": result.get("plan_run"),
                        "steps": result.get("steps"),
                        "ui": result.get("ui"),
                    },
                    "outbox_projection": outbox_projection,
                },
                metadata={
                    "team_id": team_id,
                    "thread_id": thread_id,
                    "user_id": int(ctx.user_id),
                },
            )
        except Exception as exc:
            return SkillResult(ok=False, error=str(exc), output={"type": "plan_supervisor_result"})

    @staticmethod
    def _build_outbox_projection(*, storage: Storage, team_id: int, thread_id: str) -> dict[str, Any]:
        events = storage.list_thread_events(team_id=int(team_id), thread_id=str(thread_id), limit=20)
        return {
            "events": [
                {
                    "event_id": str(item.event_id),
                    "event_type": str(item.event_type),
                    "author_type": str(item.author_type),
                    "direction": str(item.direction),
                    "origin_interface": item.origin_interface,
                    "payload_json": item.payload_json,
                    "created_at": str(item.created_at),
                }
                for item in events
            ]
        }

    @staticmethod
    def _find_step(result: dict[str, Any], step_id: str) -> dict[str, Any] | None:
        for item in list(result.get("steps") or []):
            if str(item.get("step_id")) == str(step_id):
                return item
        return None

    @staticmethod
    def _has_next_step(result: dict[str, Any]) -> bool:
        plan_run = result.get("plan_run") or {}
        return bool(plan_run.get("current_step_id"))

    @staticmethod
    def _build_directive(*, template: str, result: dict[str, Any]) -> str:
        plan_run = result.get("plan_run") or {}
        steps = list(result.get("steps") or [])
        current_step_id = plan_run.get("current_step_id")
        current_step = None
        for item in steps:
            if str(item.get("step_id")) == str(current_step_id):
                current_step = item
                break
        step_title = str((current_step or {}).get("title") or "")
        step_order = int((current_step or {}).get("order") or 0)
        return str(template).format(
            step_title=step_title,
            step_index=step_order,
            total_steps=len(steps),
            plan_run_id=str(plan_run.get("plan_run_id") or ""),
        )

    @staticmethod
    def _emit_llm_mcp_dialogue_turn(
        *,
        storage: Storage,
        team_id: int,
        thread_id: str,
        role_id: int,
        llm_text: str,
        directive_text: str,
    ) -> None:
        with storage.transaction(immediate=True):
            team_role_id = storage.resolve_team_role_id(int(team_id), int(role_id), ensure_exists=True)
            if team_role_id is None:
                raise ValueError(f"Team role not found: team_id={team_id} role_id={role_id}")
            question_id = str(uuid4())
            _ = storage.create_question(
                question_id=question_id,
                thread_id=str(thread_id),
                team_id=int(team_id),
                created_by_user_id=0,
                target_team_role_id=int(team_role_id),
                origin_type="role_dispatch",
                text=str(llm_text),
            )
            storage.create_thread_event(
                team_id=int(team_id),
                thread_id=str(thread_id),
                event_type="thread.message.created",
                author_type="role",
                direction="question",
                origin_interface="telegram",
                source_ref_type="question",
                source_ref_id=question_id,
                question_id=question_id,
                payload_json=json.dumps(
                    {
                        "kind": "child-question",
                        "text": str(llm_text),
                        "lineage": {"source_question_id": None, "parent_answer_id": None},
                    },
                    ensure_ascii=False,
                ),
                idempotency_key=f"plan-supervisor:llm-question:{question_id}",
            )
            answer_id = str(uuid4())
            _ = storage.create_answer(
                answer_id=answer_id,
                question_id=question_id,
                thread_id=str(thread_id),
                team_id=int(team_id),
                text=str(directive_text),
                team_role_id=None,
                role_name="plan_supervisor",
            )
            storage.transition_question_status(question_id=question_id, status="answered")
            storage.create_thread_event(
                team_id=int(team_id),
                thread_id=str(thread_id),
                event_type="thread.message.created",
                author_type="role",
                direction="answer",
                origin_interface="telegram",
                source_ref_type="answer",
                source_ref_id=answer_id,
                question_id=question_id,
                answer_id=answer_id,
                payload_json=json.dumps(
                    {
                        "kind": "role-answer",
                        "text": str(directive_text),
                        "lineage": {"source_question_id": None, "parent_answer_id": None},
                    },
                    ensure_ascii=False,
                ),
                idempotency_key=f"plan-supervisor:mcp-answer:{question_id}",
            )

    @staticmethod
    def _build_llm_message_for_start_plan(*, goal: str, raw_steps: list[dict[str, Any]]) -> str:
        steps = ", ".join(str((item or {}).get("title") or "").strip() for item in raw_steps if isinstance(item, dict))
        return f"start_plan: goal={goal}; steps={steps}"

    @staticmethod
    def _build_llm_message_for_report_step(*, step_id: str, summary: str) -> str:
        return f"report_step: step_id={step_id}; summary={summary}"

    def _load_merged_config(self, config: dict[str, Any]) -> dict[str, Any]:
        base: dict[str, Any] = {}
        config_path = config.get("config_path")
        path = Path(str(config_path)).expanduser() if config_path else DEFAULT_CONFIG_PATH
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    base.update(loaded)
            except Exception:
                pass
        base.update(config or {})
        return base

    def _resolve_operation(self, arguments: dict[str, Any]) -> str:
        operation_raw = arguments.get("operation")
        command_raw = arguments.get("command")
        operation = str(operation_raw or "").strip()
        command = str(command_raw or "").strip()
        if not operation and command:
            operation = command
        if operation and command and operation != command:
            raise ValueError("Conflicting fields: operation != command")
        if not operation:
            raise ValueError("operation (or legacy command) is required")
        if operation not in SUPPORTED_OPERATIONS:
            raise ValueError(f"Unsupported operation: {operation}")
        return operation

    @staticmethod
    def _normalize_operation(*, operation: str, payload: dict[str, Any]) -> str:
        # Defensive compatibility: sometimes the model keeps previous report_step intent
        # while actually sending a fresh start payload.
        if operation != "report_step":
            return operation
        has_goal = isinstance(payload.get("goal"), str) and bool(str(payload.get("goal")).strip())
        has_steps = isinstance(payload.get("steps"), list) and bool(payload.get("steps"))
        has_plan_run_id = bool(str(payload.get("plan_run_id") or "").strip())
        has_step_id = bool(str(payload.get("step_id") or "").strip())
        if has_goal and has_steps and (not has_plan_run_id) and (not has_step_id):
            return "start_plan"
        return operation

    def _resolve_team_id(
        self,
        *,
        arguments: dict[str, Any],
        payload: dict[str, Any],
    ) -> int:
        candidate = arguments.get("team_id")
        if candidate is None:
            candidate = payload.get("team_id")
        if candidate is None:
            raise ValueError("team_id is required")
        try:
            return int(candidate)
        except Exception as exc:
            raise ValueError("team_id is required and must be integer") from exc

    def _resolve_thread_id(
        self,
        *,
        arguments: dict[str, Any],
        payload: dict[str, Any],
    ) -> str:
        candidate = arguments.get("thread_id")
        if candidate is None:
            candidate = payload.get("thread_id")
        if candidate is None:
            raise ValueError("thread_id is required")
        text = str(candidate).strip()
        if not text:
            raise ValueError("thread_id is required")
        return text

    @staticmethod
    def _require_text(value: Any, field: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{field} is required")
        return text


def create_skill() -> PlanSupervisorSkill:
    return PlanSupervisorSkill()
