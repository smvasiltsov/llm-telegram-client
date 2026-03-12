# Skills SDK v1

> Архивный документ. Актуальная спецификация model-callable skills находится в `docs/skills_dev/*`.

## Purpose
SDK v1 defines a stable Python contract for local skills that can be developed and tested outside the bot, then plugged into the bot without code changes.

## Skill Layout
Each skill lives in its own folder:

```text
skills/
  <skill_id>/
    skill.yaml
    skill.py
    tests/
    mocks/
```

## Manifest (`skill.yaml`)
Required fields:
- `id`: stable skill identifier.
- `version`: semantic version string.
- `entrypoint`: Python callable path, format `module:function`.

Optional fields:
- `enabled_by_default`: bool.
- `permissions`: list of permission strings.
- `timeout_sec`: positive integer.
- `description`: free text.

## Python Contract

`describe() -> SkillSpec`
- Returns static skill metadata.

`validate_config(config: dict) -> list[str]`
- Returns validation errors (empty list if valid).

`run(ctx: SkillContext, payload: dict) -> SkillResult`
- Executes skill logic and returns structured result.
 - Runtime passes envelope:
   - `phase`: `pre` or `post`
   - `config`: role-skill config (dict)
   - `data`: mutable execution data

## Core Types
- `SkillSpec`:
  - `skill_id`, `name`, `version`, `description`
  - `permissions`, `timeout_sec`
- `SkillContext`:
  - `chain_id`, `chat_id`, `user_id`, `role_id`, `role_name`
- `SkillResult`:
  - `status` (`ok` | `error` | `skipped`)
  - `output` (dict)
  - `error` (optional text)
  - `metadata` (dict)

## Runtime Rules (v1)
- Skills are discovered at startup.
- Invalid skills are skipped, bot continues startup.
- Discovery validates:
  - manifest required fields,
  - entrypoint import,
  - required functions existence.
- Execution (iteration 1):
  - `pre` phase may override:
    - `data.user_text`
    - `data.reply_text`
  - `post` phase may override:
    - `data.response_text`
  - Skill errors are logged and do not break role pipeline.
  - Guardrails:
    - timeout per skill: from manifest `timeout_sec` (clamped to 1..120 sec),
    - max output size: 12000 chars (JSON-serialized output),
    - permissions allowlist:
      - `read_context`
      - `transform_prompt`
      - `transform_response`
    - skills with unsupported permissions are skipped.

## Testing Outside Bot
- Skill should be runnable with mock context and mock payload.
- Recommended:
  - unit tests in `skills/<id>/tests/`
  - canned inputs in `skills/<id>/mocks/`
