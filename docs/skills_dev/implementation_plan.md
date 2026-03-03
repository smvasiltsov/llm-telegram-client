# Skills System Implementation Plan

## Goal

Add a new model-callable `skills` system without disturbing the current `prepost_processing` infrastructure.

## Guiding constraints

- no second LLM roundtrip for skill selection in v1;
- no runtime prefiltering by tags in v1;
- every skill must be enabled or disabled per role;
- read-only skills first;
- mutation and dangerous skills only after the base loop is stable.

## Phase 1. Define contracts and boundaries

Deliverables:

- create `app/skills/` package;
- add contracts for:
  - `SkillSpec`
  - `SkillContext`
  - `SkillResult`
  - `SkillProtocol`
- add a dedicated skill registry;
- keep `prepost_processing` untouched except for runtime wiring changes needed to coexist with `skills`.

Notes:

- do not reuse old pre/post hook contracts for model-callable skills;
- keep naming fully separated in code and docs.

## Phase 2. Storage and runtime wiring

Deliverables:

- add storage tables for:
  - role-enabled skills
  - skill execution logs
  - optional conversation run metadata
- extend `RuntimeContext` with:
  - `skills_registry`
  - `skills_service`
- add storage methods for enabling, disabling, listing, and logging skills.

Notes:

- migrations must preserve future compatibility;
- skill logs must store arguments, result status, error text, and duration.

## Phase 3. Assistant protocol and parser

Deliverables:

- define the assistant JSON protocol:
  - `final_answer`
  - `skill_call`
- add a parser for assistant decisions;
- add clear parse-error handling and fallback behavior.

Notes:

- v1 supports one skill call per assistant step;
- output parser must be provider-agnostic.

## Phase 4. Skill-calling loop

Deliverables:

- add `app/services/skill_calling_loop.py`;
- implement the loop:
  - load enabled skills for the role;
  - build skill catalog;
  - call the LLM;
  - parse decision;
  - execute skill if requested;
  - append skill result;
  - continue until final answer or limit.

Loop guards:

- max steps;
- max repeated identical calls;
- timeout budget;
- structured error propagation.

## Phase 5. First built-in filesystem skills

Deliverables:

- implement `fs.read_file`;
- implement `fs.list_dir`;
- implement `fs.write_file`.

Notes:

- keep filesystem access inside configured roots;
- support bounded range reads for `fs.read_file`;
- support create, replace, and append behavior for `fs.write_file`.

## Phase 6. Role UI for skill management

Deliverables:

- add a separate role UI screen for `Skills`;
- allow enable/disable per role;
- show short descriptions and safety class.

Notes:

- do not merge this UI with `Pre/Post Processing`;
- storage and callback names should stay distinct.

## Phase 7. Observability and test coverage

Deliverables:

- add unit tests for registry, parser, runtime validation, and built-in skills;
- add integration tests for the loop;
- add audit-friendly logs for skill decisions and results.

Minimum test matrix:

- disabled skill call rejected;
- schema validation error;
- read-only file read success;
- file write success;
- loop exits on final answer;
- loop exits on repeated bad calls.

## Phase 8. External developer kit

Deliverables:

- prepare a standalone repository seed for independent AI developers;
- include SDK, runner, template skill, tests, docs, and bootstrap prompt;
- ensure skills built there can be copied into the main repo and work without provider access.

Notes:

- the external kit must not depend on bot runtime modules;
- local testing must work without access to a real LLM provider.

## Phase 9. Documentation and examples

Deliverables:

- add developer docs for adding a new model-callable skill;
- add examples of input schemas and result payloads;
- document how role skill enablement affects the visible skill catalog.

## Recommended implementation order

1. Contracts and registry.
2. Storage and runtime wiring.
3. Assistant protocol and parser.
4. Skill-calling loop.
5. Built-in filesystem skills.
6. Role UI for enable/disable.
7. Tests and observability hardening.
8. External developer kit.

## Non-goals for v1

- second LLM roundtrip for skill selection;
- tag-based or embedding-based prefiltering;
- parallel skill calls;
- multi-skill calls in one assistant response;
- approval workflows for dangerous skills.

These can be added after the first stable version is working in production.
