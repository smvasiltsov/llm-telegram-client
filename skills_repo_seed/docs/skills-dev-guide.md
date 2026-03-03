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
