# Skills Protocol

## Design principle

The LLM must not guess how to trigger a capability from free text. It must respond with an explicit structured decision that the runtime can parse deterministically.

## Assistant decisions

Each assistant step may return either:

- a `skill_call` JSON object
- a normal plain-text answer for the user
- optionally a `final_answer` JSON object for compatibility

## Plain-text answer

If the model does not want to use a skill, it may answer with normal text.

That plain text is treated as the final user-facing answer.

## Optional `final_answer` shape

```json
{
  "type": "final_answer",
  "answer": {
    "text": "Final user-facing answer"
  }
}
```

## `skill_call` shape

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

## Skill result shape

Successful result:

```json
{
  "ok": true,
  "skill_id": "fs.read_file",
  "result": {
    "path": "README.md",
    "content": "..."
  }
}
```

Error result:

```json
{
  "ok": false,
  "skill_id": "fs.read_file",
  "error": {
    "code": "not_found",
    "message": "File not found"
  }
}
```

## Catalog shape sent to the LLM

The first iteration sends a single compact catalog with each normal request. Every visible skill in the catalog must already be enabled for the current role.

Example:

```json
{
  "skills": [
    {
      "skill_id": "fs.read_file",
      "description": "Read a UTF-8 text file from the allowed workspace.",
      "mode": "read_only",
      "input_schema": {
        "type": "object",
        "properties": {
          "path": {
            "type": "string"
          }
        },
        "required": ["path"]
      }
    },
    {
      "skill_id": "web.search",
      "description": "Search the web and return compact result snippets.",
      "mode": "read_only",
      "input_schema": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string"
          }
        },
        "required": ["query"]
      }
    }
  ]
}
```

## Runtime guarantees

The runtime must:

- reject unknown `skill_id`;
- reject invalid arguments;
- reject disabled skills;
- reject calls that violate role policy;
- clamp output size;
- return a structured error instead of crashing the chat flow.

## Loop rules

The first iteration should enforce:

- max one skill call per assistant step;
- max total steps per run;
- max repeated identical calls;
- structured fallback if the assistant output cannot be parsed.

## Why this protocol matters

This protocol gives:

- predictable runtime behavior;
- provider-independent integration;
- auditability for every skill call;
- a clean path to more advanced features later, such as multi-call steps or filtered catalogs.
