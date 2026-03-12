---
title: 40.4 Skills Runner (CLI)
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5931009
  parent_doc_path: 40-skills-and-mcp-platform/_index.md
  local_id: 40-4-skills-runner-cli
  parent_local_id: 40-skills-and-mcp-platform
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 40.4 Skills Runner (CLI)

## Purpose
`skills_runner.py` provides direct terminal execution of model-callable skills without Telegram interaction or LLM roundtrip.

File:
- `scripts/skills_runner.py`

## Main Capabilities
- discover skills via `app.skills.SkillRegistry`,
- print skill contracts (`input_schema`),
- execute a selected skill with mock context fields.

## Commands

### List skills
```bash
python3 scripts/skills_runner.py --skills-dir skills list
```

Optional single-skill filter:
```bash
python3 scripts/skills_runner.py --skills-dir skills list --skill-id fs.read_file
```

### Execute a skill
```bash
python3 scripts/skills_runner.py \
  --skills-dir skills \
  exec \
  --skill-id fs.list_dir \
  --arguments-json '{"path":"."}' \
  --config-json '{"root_dir":"/tmp"}'
```

## Input Sources
Arguments and config can be passed:
- inline JSON (`--arguments-json`, `--config-json`),
- JSON files (`--arguments-file`, `--config-file`).

Inline JSON overrides file values when both are supplied.

## Exit Codes
- `0`: success
- `1`: invalid JSON or CLI input
- `2`: skill not found
- `3`: skill config validation failed

## Typical Use Cases
- contract verification,
- config validation checks,
- reproducible local debugging of skill behavior.
