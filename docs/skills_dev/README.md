# Skills Development Docs

This section describes the future model-callable `skills` system.

## Terminology

- `prepost_processing` - deterministic server-side hooks that run before or after an LLM call.
- `skills` - model-callable capabilities such as file reading, file writing, SQL queries, and web search.
- `orchestrator` - the runtime loop that sends context to the LLM, interprets `final_answer` vs `skill_call`, executes skills, and continues the conversation until completion.

## Scope of the first skills iteration

The first version of the skills system is intentionally simple:

- no second LLM roundtrip for skill selection;
- no runtime prefiltering by tags or embeddings;
- per-role enable/disable for each visible skill;
- one explicit skill catalog sent with the main LLM request;
- one structured assistant decision per step:
  - `final_answer`
  - `skill_call`

This keeps the first implementation understandable and debuggable. More advanced catalog-reduction strategies can be added later.

## Recommended reading order

1. `docs/skills_dev/architecture.md`
2. `docs/skills_dev/protocol.md`
3. `docs/skills_dev/implementation_plan.md`
4. `docs/skills_dev/developer_guide.md`

## Why this split exists

The project already has a working hook system under `prepost_processing/`. That mechanism is appropriate for automatic input/output transformations, but not for explicit LLM-directed actions.

Examples:

- Good `prepost_processing`:
  - normalize Telegram text;
  - attach deterministic local context;
  - sanitize markdown before send.
- Good `skills`:
  - read a file;
  - list a directory;
  - write or append a file.

## Initial design goals

- keep `skills` and `prepost_processing` strictly separate;
- make each skill invocation observable and auditable;
- support safe read-only skills first;
- add mutation and dangerous skills only after the execution loop is stable;
- keep provider integration generic, so the same loop can work with different LLM backends.
