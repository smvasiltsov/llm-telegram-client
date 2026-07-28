# Plan Supervisor Skill Rollout

## Current State
- `plan_supervisor` is implemented as a regular skill in `skills/plan_supervisor/*`.
- Tool-version is removed.
- No global `features` flags are required for loading this skill.

## Enablement Model
- Skill discovery: automatic from `skills/` directory.
- Runtime usage: controlled per role via existing role-skill bindings (`role_skills_enabled`).
- Access policy: controlled by skill config (`require_owner`, `strict_mode`, `owner_user_id`, etc.).

## Migration for Existing Roles
1. Add/keep skill `plan_supervisor` in role skills list.
2. Configure role-level skill config (owner and context defaults).
3. Validate happy path and transition errors on staging.
4. Roll out to production roles incrementally.

## Rollback
- Disable the skill on affected roles (no global switch needed).
- Keep other skills unchanged.
