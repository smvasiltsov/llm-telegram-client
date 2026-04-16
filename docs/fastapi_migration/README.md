# LTC-36: FastAPI Migration Analysis

## Scope
- Source of truth: `app/*` and `tests/*`.
- Excluded: experimental/draft materials (`docs/temp/*` and similar non-runtime artifacts).
- Goal: assess readiness of current domain/runtime model for FastAPI management API over existing functionality.

## Documents
- `01_domain_model_as_is.md` — current domain model and ER-level relationships.
- `02_api_readiness_assessment.md` — readiness assessment, limitations, and gaps.
- `03_refactoring_and_target_fastapi_architecture.md` — refactoring recommendations and target FastAPI structure.
- `04_migration_roadmap_and_risks.md` — phased rollout plan, risks, and mitigations.
- `05_stage2_entry_execution_checklist.md` — execution checklist with Stage 2 GO blockers and strict v1 DTO/OpenAPI contract.
- `06_stage2_v1_api_runbook.md` — quick runbook for standalone read-only API launch.
- `07_stage2_v1_signoff.md` — Stage 2 v1 sign-off: delivered scope, out-of-scope, residual risks.
- `08_telegram_operations_inventory.md` — inventory of Telegram user-intent operations and Stage 2 GET candidates.
- `09_stage2_read_api_extension_checklist.md` — baseline and acceptance criteria for Stage 2 read API extension (`roles/catalog`, `catalog/errors`, `team sessions`).
- `10_stage3_write_api_execution_checklist.md` — baseline and blocking acceptance checklist for Stage 3 v1 write/mutation/orchestration API.
- `11_stage3_write_api_contracts.md` — API contracts for Stage 3 v1 write endpoints (DTO, statuses, error envelope, idempotency semantics).
- `12_stage3_v1_write_api_runbook.md` — runbook for Stage 3 v1 write API launch and smoke checks.
- `13_stage3_v1_signoff.md` — Stage 3 v1 sign-off: delivered write scope, non-scope, risks and consistency notes.
- `14_stage5_qa_api_orchestration_spec.md` — Stage 5 Q/A orchestration architecture/spec.
- `15_stage4_runtime_api_hardening_checklist.md` — Stage 4 baseline and blocking checklist (observability, single-instance policy, smoke/integration, CI/sign-off).
- `16_stage4_runtime_api_hardening_runbook.md` — Stage 4 operations runbook: runtime modes, Stage 4 metrics/alerts, incident playbooks, rollback.
- `17_stage4_runtime_api_hardening_signoff.md` — Stage 4 final sign-off: checklist closure, GO/NO-GO, timestamp, CI/artifact references, Stage 2/3/4/5 consistency notes.
- `18_stage5_qa_api_execution_checklist.md` — Stage 5 v1 baseline and blocking checklist (scope, status machine, error codes, DB idempotency, cursor policy, authz, UoW boundaries, CI/DoD).
- `19_stage5_qa_api_runbook.md` — Stage 5 runbook: Q/A API semantics, idempotency/cursor/orchestrator-feed operations, smoke and incident notes.
- `20_stage5_qa_api_signoff.md` — Stage 5 v1 sign-off: checklist closure, GO/NO-GO, CI/job links, done/out-of-scope/risks.
- `28_stage5_three_process_runbook.md` — запуск и smoke для режима `runtime + api + telegram`.
- `29_stage5_event_bus_outbox_runbook.md` — runbook по Universal Thread Event Bus + Outbox delivery + admin API + observability.

## Common Template
Each document follows a unified template:
1. Purpose and boundaries.
2. As-is findings.
3. Constraints and gaps.
4. Recommendations/decisions.
5. Traceability (file/function references).

## Acceptance Criteria Coverage
1. Описание текущей доменной модели (role/team/team_role/channel binding/skills/session/messages/role params):
   - Covered by `01_domain_model_as_is.md` (включая ER-уровень и runtime-flow).
2. Оценка готовности к FastAPI с ограничениями и пробелами:
   - Covered by `02_api_readiness_assessment.md`.
3. Рекомендации по рефакторингу и пошаговым доработкам перед API:
   - Covered by `03_refactoring_and_target_fastapi_architecture.md`.
4. Отдельный поэтапный план внедрения и риски:
   - Covered by `04_migration_roadmap_and_risks.md`.
5. Трассируемость на фактический код:
   - Во всех документах есть разделы с ссылками на `app/*` и подтверждающие `tests/*`.
