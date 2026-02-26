# AGENTS.md (skills-only repository)

## Mission
You work only on MCP skills. Do not modify bot runtime code.

## Scope
Allowed:
- `skills/<skill_id>/...`
- `mcp_skill_sdk/...`
- `scripts/...`
- `tests/...`
- `docs/...`

Forbidden:
- Telegram bot handlers, storage, router, orchestrator logic from another repo.

## Skill Contract
Every skill must implement:
- `describe() -> SkillSpec`
- `validate_config(config: dict) -> list[str]`
- `run(ctx: SkillContext, payload: dict) -> SkillResult`

## Skill Folder Standard
Each skill must include:
- `skills/<skill_id>/skill.yaml`
- `skills/<skill_id>/skill.py`
- `skills/<skill_id>/__init__.py`

## Validation Checklist (before done)
1. `python3 scripts/skill_runner.py --skill-id <id> --phase pre --payload-json '{"user_text":"ping"}'`
2. If config is used, validate both valid and invalid config paths.
3. Keep output JSON small and deterministic.
4. No network calls by default unless explicitly requested.

## Coding Rules
- Keep logic simple, deterministic, and testable.
- Use ASCII unless non-ASCII is required.
- Add short comments only for non-obvious code.
