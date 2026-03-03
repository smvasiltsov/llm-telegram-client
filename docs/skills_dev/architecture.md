# Skills System Architecture

## Architectural split

The target project model is:

- `prepost_processing` - automatic middleware around the LLM call.
- `skills` - model-callable actions.
- `orchestrator` - the loop that coordinates the model and the skills runtime.

These concepts must stay separate in code, storage, and UI.

## Four layers

### 1. Skill Registry

Responsibilities:

- register all available skills;
- expose compact metadata for prompt building;
- expose full input schema for runtime validation;
- describe permissions, timeout, and safety class;
- resolve `skill_id -> executor`.

Planned code area:

- `app/skills/contract.py`
- `app/skills/registry.py`

Expected core entities:

- `SkillSpec`
- `SkillContext`
- `SkillResult`
- `SkillProtocol`

Recommended `SkillSpec` fields:

- `skill_id`
- `name`
- `description`
- `input_schema`
- `mode`:
  - `read_only`
  - `mutating`
  - `dangerous`
- `timeout_sec`
- `max_result_bytes`

## 2. Agent / Orchestrator Loop

Responsibilities:

- build LLM input from role prompt, user request, prior steps, and enabled skills;
- send the request to the LLM;
- parse the structured assistant decision;
- either finish with `final_answer` or execute a `skill_call`;
- append the skill result to the conversation state;
- continue until stop conditions are met.

Planned code area:

- `app/services/skill_calling_loop.py`

Loop stop conditions:

- final answer returned;
- max steps exceeded;
- repeated same-call loop detected;
- global timeout budget exhausted;
- unrecoverable parse failure.

## 3. Skill Runtime

Responsibilities:

- validate skill arguments against schema;
- enforce role-level access rules;
- execute the skill safely;
- normalize output into a predictable result envelope;
- persist logs and execution metadata.

Planned code area:

- `app/skills/runtime.py`
- `app/skills/service.py`
- `app/skills/errors.py`
- `app/skills/builtin/`

Built-in skill families planned for the first phases:

- filesystem:
  - `fs.read_file`
  - `fs.list_dir`
  - later `fs.write_file`
  - later `fs.apply_diff`
- SQL:
  - `sql.query_readonly`
- web:
  - `web.search`
  - `web.fetch_page`

## 4. Conversation State

Responsibilities:

- persist step-by-step assistant decisions;
- persist every skill call and skill result;
- allow auditing and debugging;
- support retry and post-mortem analysis.

Planned storage concepts:

- `conversation_runs`
- `conversation_steps`
- `role_skills_enabled`
- `skill_runs`

This state should be separate from the current session and message state used for generic LLM provider sessions.

## Request pipeline

The target runtime flow:

1. Telegram handler routes a message to a role.
2. `prepost_processing` runs on the input.
3. Role pipeline starts the skill-calling loop.
4. The loop loads role-enabled skills from storage.
5. The loop builds a compact skill catalog.
6. The LLM returns either:
   - `final_answer`
   - `skill_call`
7. If a `skill_call` is returned, runtime validates and executes it.
8. The skill result is appended to state and returned to the LLM.
9. The loop continues until a final answer is produced.
10. `prepost_processing` runs on the final output.
11. Telegram handler sends the final text.

## First-iteration constraints

The first iteration deliberately does not include:

- second LLM roundtrip for skill discovery;
- runtime prefiltering by tags;
- parallel skill execution;
- multi-skill assistant decisions in one step;
- human approval flow for mutations.

The first iteration does include:

- per-role enable/disable of each skill;
- one-shot catalog included in the normal LLM call;
- one `skill_call` per assistant step;
- structured errors returned to the model;
- execution logging in SQLite.

## UI split

Role configuration must expose two independent concepts:

- `Pre/Post Processing`
- `Skills`

They should not share the same callbacks, storage table, or naming.

## Security model

Each skill must declare a safety class:

- `read_only` - safe read operations with bounded output.
- `mutating` - changes files or state.
- `dangerous` - high-risk operations such as shell execution.

Security rules for the first version:

- implement read-only skills first;
- keep filesystem skills constrained to an allowed root;
- keep SQL read-only by contract and runtime enforcement;
- keep web access bounded by timeout and result truncation;
- postpone dangerous skills until the loop and logging are stable.
