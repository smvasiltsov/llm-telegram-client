# MCP Skills Isolated Workspace

This directory is a seed for a separate repository where another LLM agent can build skills without bot context.

## Structure
- `mcp_skill_sdk/` - local SDK contract and registry.
- `skills/` - skill implementations.
- `scripts/` - local runner and publish helpers.
- `tests/` - unit/smoke tests.
- `docs/` - development guide.
- `prompts/` - bootstrap prompt for a new agent.

## Quick Start
1. `python3 -m venv .venv`
2. `source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `python3 scripts/skill_runner.py --skill-id echo --phase pre --payload-json '{"user_text":"hello"}'`

## Publish to bot repo
Use `scripts/publish_to_bot_skills.sh` to copy selected skills into a bot repository `skills/` folder.
