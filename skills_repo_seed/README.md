# Standalone Skills Developer Kit

This folder is a self-contained seed for a separate repository where independent AI developers can build model-callable `skills` without access to the main bot project or any real LLM provider.

## What is included

- `skills_sdk/` - standalone SDK contract and registry
- `skills/` - local skill implementations
- `scripts/` - local runner and publish helper
- `tests/` - smoke tests for discovery and local execution
- `docs/` - everything an external developer needs to understand and implement skills
- `prompts/` - bootstrap prompt for a new AI developer

## Real example included

This kit now includes a real filesystem skill example:

- `fs.read_file`

It follows the same implementation pattern and uses the same standard-library dependencies as the production skill in the main project.

## What external developers should do first

1. Read `AGENTS.md`
2. Read `docs/quickstart.md`
3. Read `docs/skills-sdk-v1.md`
4. Read `docs/skills-dev-guide.md`
5. Read `prompts/agent_bootstrap_prompt.md`

## No provider dependency

This kit does not need access to a real LLM provider.

Skills are developed and tested through:

- direct local execution with `scripts/skill_runner.py`
- local smoke tests
- registry validation

## Main integration rule

A skill developed here should work in the main project out of the box if:

- it uses the same `skills_sdk` contract;
- the manifest is valid;
- it is copied into the main repo `skills/` folder;
- it is enabled for a role in the bot UI;
- the role skill config is valid.
