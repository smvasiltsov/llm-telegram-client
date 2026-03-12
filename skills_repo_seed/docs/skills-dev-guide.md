# Skills Development Guide

## Goal

Build a model-callable skill that can be copied into the main bot repository and work there without code changes.

## Folder layout

Each skill must live in:

```text
skills/<skill_folder>/
  __init__.py
  skill.yaml
  skill.py
```

## Required Python contract

Your skill must implement:

- `describe() -> SkillSpec`
- `validate_config(config: dict) -> list[str]`
- `run(ctx: SkillContext, arguments: dict, config: dict) -> SkillResult`

## Critical: where LLM contract must be described

The runtime builds LLM-visible skill contracts from `describe()` only.

It does **not** build the main contract from `README.md`.

For each skill, the following fields are sent to LLM (via `skills.available`):

- `skill_id`
- `name`
- `description`
- `input_schema`
- `mode`

Therefore:

1. Put complete operational contract text into `SkillSpec.description`:
   - what the skill does;
   - required/optional argument rules;
   - mode behavior;
   - config prerequisites (for example `config.root_dir`).
2. Put strict argument structure into `SkillSpec.input_schema`:
   - `type`, `properties`, `required`;
   - `enum`, `oneOf`, `minimum/maximum`, `default` where needed;
   - per-field `description` for ambiguous fields.
3. Keep `README.md` for humans; do not rely on README as the primary LLM contract source.

If `skills_prompt_preview.py` shows weak contracts, improve `description` and `input_schema` in `describe()`.

## Multi-mode skills (single skill_id with multiple modes)

If one skill supports multiple modes, encode modes directly in `input_schema`.

Recommended pattern:

- `mode` field with explicit enum.
- Mode-specific branches via `oneOf`.
- Per-branch required fields with `const` on `mode`.

Conceptual example:

```json
{
  "type": "object",
  "properties": {
    "mode": { "type": "string", "enum": ["read", "write"] }
  },
  "required": ["mode"],
  "oneOf": [
    {
      "properties": {
        "mode": { "const": "read" },
        "path": { "type": "string" }
      },
      "required": ["mode", "path"]
    },
    {
      "properties": {
        "mode": { "const": "write" },
        "path": { "type": "string" },
        "content": { "type": "string" }
      },
      "required": ["mode", "path", "content"]
    }
  ]
}
```

This is the most reliable way to make the LLM form correct arguments for each mode.

## Design expectations

- deterministic behavior
- bounded output
- explicit config validation
- no imports from Telegram or main bot runtime
- JSON-like output only

## Real example

Use `skills/fs_read_file/` as the production-like example.

It mirrors the main project style:

- shared helper module in `skills/_fs_common.py`
- `pathlib` for path handling
- config validation through `validate_config`
- strict root-dir confinement
- UTF-8 text handling

## Local testing

```bash
python3 scripts/skill_runner.py \
  --skills-dir skills \
  --skill-id echo.skill \
  --arguments-json '{"message":"hello"}' \
  --config-json '{}'
```

Smoke tests:

```bash
python3 -m unittest discover -s tests -v
```

## Preview LLM-visible skill contracts

Use the prompt preview script to inspect the exact `skills` section that is sent to LLM (`skills.prompt`, `skills.available`, `skills.history`).

```bash
python3 scripts/skills_prompt_preview.py \
  --skills-dir skills \
  --enabled-skill-id fs.read_file \
  --enabled-skill-id fs.list_dir \
  --output input_json
```

Useful modes:

- `--output skills_only` - print only the `skills` object
- `--output input_json_compact` - print compact `INPUT_JSON` exactly like bot runtime sends
- `--history-json '[{"skill_id":"fs.read_file","ok":true,"status":"ok","output":{"path":"README.md"},"error":null}]'`
- Debug metadata is included by default (`manifest`, `version`, `timeout_sec`, config hints from `validate_config({})`)
- `--no-include-debug-meta` - hide debug metadata
- `--include-readme --readme-max-chars 1500` - include README excerpt for each skill (if present)
