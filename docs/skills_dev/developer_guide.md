# Developer Guide For Model-Callable Skills

This guide describes how to create a new model-callable `skill` for this project.

## What a skill is

A `skill` is a runtime capability that the LLM may explicitly call.

Examples:

- `fs.read_file`
- `fs.list_dir`
- `fs.write_file`

A skill is not the same thing as `prepost_processing`.

- `prepost_processing` is automatic middleware around the LLM call.
- `skills` are explicit actions selected by the LLM through the `skill_call` protocol.

## Required files

Each skill lives in:

```text
skills/<skill_folder>/
  __init__.py
  skill.yaml
  skill.py
```

## Manifest

`skill.yaml` must contain:

```yaml
id: fs.read_file
version: 0.1.0
entrypoint: skill:create_skill
```

Rules:

- `id` is the runtime `skill_id` visible to the LLM.
- `version` is the skill version.
- `entrypoint` must point to a factory that returns the skill instance.

## Python contract

Each skill must implement:

- `describe() -> SkillSpec`
- `validate_config(config: dict) -> list[str]`
- `run(ctx: SkillContext, arguments: dict, config: dict) -> SkillResult`

Contract types are defined in:

- [contract.py](/opt/llm/llm-telegram-client-in-dev/skills_sdk/contract.py)

## Design rules

- Keep the skill deterministic.
- Do not import Telegram bot handlers or other bot runtime modules.
- Return JSON-like output only.
- Validate config early.
- Prefer explicit errors over implicit fallback.
- Keep results bounded in size.

## Local development without LLM provider

Use the standalone developer kit in `skills_repo_seed/`.

That folder contains:

- standalone `skills_sdk`
- discovery registry
- local runner
- template skill
- smoke tests
- developer prompt

## Integration expectation

If a developer creates a skill in the standalone kit and copies the finished `skills/<folder>/` into this repository, it should work out of the box as long as:

- the skill uses the same SDK contract;
- the manifest is valid;
- the skill is enabled for a role;
- required config is provided for that role.
