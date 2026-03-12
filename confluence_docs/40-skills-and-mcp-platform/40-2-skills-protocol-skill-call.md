---
title: 40.2 Skills Protocol (skill_call)
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5865473
  parent_doc_path: 40-skills-and-mcp-platform/_index.md
  local_id: 40-2-skills-protocol-skill-call
  parent_local_id: 40-skills-and-mcp-platform
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 40.2 Skills Protocol (skill_call)

## Protocol Goal
The skills protocol makes assistant decisions deterministic: instead of free-text tool hints, the model returns a strict JSON action when it wants runtime capability execution.

## Accepted Assistant Outcomes
For each loop step, LTC accepts:
- plain text final answer,
- explicit `skill_call` JSON object,
- optional `final_answer` JSON compatibility shape.

## Canonical `skill_call` Shape
```json
{
  "type": "skill_call",
  "skill_call": {
    "skill_id": "fs.read_file",
    "arguments": {
      "path": "README.md"
    }
  }
}
```

## Skill Catalog Provided to Model
Each request includes `skills` section with:
- `prompt`: usage instructions for model,
- `available`: enabled skills and their schemas,
- `history`: executed skill results for current loop.

Only role-enabled skills are exposed.

## Runtime Guarantees
LTC runtime enforces:
- unknown `skill_id` rejection,
- argument schema validation,
- disabled-skill rejection,
- bounded output handling,
- structured error return instead of unhandled failures.

## Loop Guardrails
Skill loop applies safety limits:
- max steps per request,
- repeated identical call detection,
- parse fallback behavior.

If parsing fails or guard limit is hit, the system exits with deterministic fallback output.

## Skill Result Contract
Runtime returns normalized success/error envelopes, so the model can reason over outputs consistently in follow-up steps.
