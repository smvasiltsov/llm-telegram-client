---
title: 40.3 Skills Developer Guide
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5898241
  parent_doc_path: 40-skills-and-mcp-platform/_index.md
  local_id: 40-3-skills-developer-guide
  parent_local_id: 40-skills-and-mcp-platform
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 40.3 Skills Developer Guide

## Skill Packaging Model
Each model-callable skill is a folder under `skills/` with three core files:
- `skill.yaml`
- `skill.py`
- `__init__.py`

## Manifest Contract
`skill.yaml` defines runtime identity and factory entrypoint.
Required fields:
- `id` (runtime `skill_id`),
- `version`,
- `entrypoint` (for example `skill:create_skill`).

## Python Contract
A skill implementation is expected to provide:
- `describe() -> SkillSpec`
- `validate_config(config: dict) -> list[str]`
- `run(ctx: SkillContext, arguments: dict, config: dict) -> SkillResult`

Contract types come from `skills_sdk/contract.py`.

## Development Rules
- Keep behavior deterministic.
- Validate inputs and config early.
- Return JSON-serializable output only.
- Bound output size.
- Return explicit errors instead of silent fallback.
- Avoid coupling skills to Telegram handler internals.

## Integration into LTC Runtime
For production use, a skill must satisfy:
- valid manifest and entrypoint,
- successful discovery by registry,
- role-level enablement in LTC UI/storage,
- required role config provided.

## Local Development Tooling
Standalone dev utilities are available in `skills_repo_seed/` for building and testing skills before enabling them in bot runtime.
