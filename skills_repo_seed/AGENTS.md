# AGENTS.md (standalone skills repository)

## Mission
You work only on model-callable `skills`.

Do not implement Telegram handlers, storage migrations, provider adapters, or other bot runtime code from the main repository.

## Scope

Allowed:

- `skills/<skill_folder>/...`
- `skills_sdk/...`
- `scripts/...`
- `tests/...`
- `docs/...`
- `prompts/...`

Forbidden:

- bot handlers
- Telegram UI code
- provider/router/session logic from the main project

## Read first

1. `docs/quickstart.md`
2. `docs/skills-sdk-v1.md`
3. `docs/skills-dev-guide.md`
4. `docs/publish-workflow.md`
5. `prompts/agent_bootstrap_prompt.md`

## Skill contract

Every skill must implement:

- `describe() -> SkillSpec`
- `validate_config(config: dict) -> list[str]`
- `run(ctx: SkillContext, arguments: dict, config: dict) -> SkillResult`

## Local validation checklist

1. Run the local runner:
   - `python3 scripts/skill_runner.py --skill-id <id> --arguments-json '{"x":1}' --config-json '{}'`
2. If config is used, test both valid and invalid config.
3. Run smoke tests:
   - `python3 -m unittest discover -s tests -v`
