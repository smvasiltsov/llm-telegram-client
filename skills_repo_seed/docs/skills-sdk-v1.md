# Skills SDK v1

This repository mirrors the model-callable `skills` contract used by the main bot project.

## Contract objects

### `SkillSpec`

Describes the skill visible to runtime and LLM.

Important fields:

- `skill_id`
- `name`
- `version`
- `description`
- `input_schema`
- `mode`
- `timeout_sec`

Important: LLM call contracts are derived from `SkillSpec.description` and `SkillSpec.input_schema`.
Do not keep primary argument contract details only in README.
If a skill has multiple modes, encode mode-specific argument contracts in `input_schema` (for example via `oneOf` + `mode` discriminator).

### `SkillContext`

Runtime metadata passed to the skill:

- `chain_id`
- `chat_id`
- `user_id`
- `role_id`
- `role_name`

### `SkillResult`

Return object for the skill:

- `ok`
- `output`
- `error`
- `metadata`

## Protocol

Every skill must implement:

```python
def describe(self) -> SkillSpec: ...
def validate_config(self, config: dict[str, Any]) -> list[str]: ...
def run(self, ctx: SkillContext, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult: ...
```

## Discovery

Skills are discovered from:

```text
skills/<skill_folder>/skill.yaml
skills/<skill_folder>/skill.py
```

The registry loads:

- manifest from `skill.yaml`
- factory from `entrypoint`
- returned instance from `create_skill()`

## Reference example

For a production-like example, inspect:

- `skills/fs_read_file/skill.py`
- `skills/_fs_common.py`

That example is intentionally aligned with the real filesystem skill pattern used in the main project.
