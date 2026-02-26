# MCP Skills Platform: Iteration 1 Plan

## Goal
- Add a minimal skills platform for roles:
  - auto-discovery of local skills,
  - role-to-skill binding in storage (next steps),
  - pipeline-ready execution contract.

## Scope of Iteration 1
- In scope:
  - skill SDK v1 contract,
  - skill folder standard,
  - discovery/registry skeleton with validation,
  - docs for developers.
- Out of scope:
  - remote marketplace,
  - full sandbox isolation,
  - advanced orchestration policies.

## Step Breakdown
1. Define SDK v1 contract. (done)
2. Define skill folder and manifest format. (done)
3. Implement `SkillRegistry` auto-discovery skeleton. (done)
4. Add DB model for role-skill binding.
5. Integrate skill pre/post hooks into role pipeline.
6. Add guardrails (timeout, output limit, permissions).
7. Add basic Telegram UI for enable/disable per role.
8. Add local skill runner (mock-friendly).
9. Add tests (unit + integration smoke). (done)
10. Update docs and acceptance checklist.

## Step 1 Deliverables
- `docs/mcp/skills-sdk-v1.md`
- `app/mcp/skills_contract.py`
- `app/mcp/registry.py`

## Current Progress
- Done:
  - SDK v1 contract docs
  - `app.mcp` contracts
  - registry discovery
  - runtime bootstrap discovery on startup
  - `skills/_template` and `skills/echo` examples
  - DB table and storage API for role-skill bindings (`role_skills`)
  - pre/post skill hooks integrated into role pipeline (`execute_role_request`)
  - guardrails in pipeline:
    - timeout,
    - output size limit,
    - permissions allowlist
  - basic Telegram UI:
    - role screen -> skills screen,
    - enable/disable skill toggle for role
  - local skill runner (`scripts/skill_runner.py`) for mock execution outside bot
  - tests:
    - `tests/test_mcp_registry.py`
    - `tests/test_storage_role_skills.py`
    - `tests/test_skill_runner_smoke.py`
- Next:
  - finalize docs + acceptance checklist

## Acceptance Criteria (Iteration 1)
- Skill added into `skills/<id>/` is discovered on bot start.
- Invalid skill is skipped with explicit error log.
- Role pipeline can reference registry (integration in later step).
- Contract is stable and documented for external developers.
