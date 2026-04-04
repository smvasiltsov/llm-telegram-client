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
