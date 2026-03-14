# Role JSON Authoring Guide for AI Agents

## Purpose
This guide defines how an AI agent should create and maintain role JSON files for LTC.

## File Placement
- Directory: `roles_catalog/`
- One role per file
- Extension: `.json`

## Identity
- Identity is the file basename only.
- Example: `roles_catalog/researcher.json` -> role identity `researcher`.
- Valid basename regex: `^[a-z0-9_]+$`
- Do not use uppercase letters, spaces, or dashes in file names.

## Required vs Optional Fields
Required (must exist as canonical or alias):
- `base_system_prompt` (aliases: `system_prompt`, `prompt`)

Optional:
- `description` (alias: `summary`)
- `extra_instruction` (alias: `instruction`)
- `llm_model` (alias: `model`)
- `is_active` (aliases: `active`, `enabled`)
- `schema_version` (must be `1` if present)
- `role_name` (metadata only, ignored for identity)

## Recommended Canonical JSON
```json
{
  "schema_version": 1,
  "role_name": "researcher",
  "description": "Research-focused role",
  "base_system_prompt": "You are a research assistant.",
  "extra_instruction": "Answer with concise bullet points.",
  "llm_model": null,
  "is_active": true
}
```

## Minimal Valid JSON
```json
{
  "base_system_prompt": "You are a helpful assistant."
}
```

## Invalid Example
```json
{
  "base_system_prompt": 123,
  "is_active": "yes"
}
```
Invalid because field types are wrong.

## Validation and Errors
Typical catalog errors:
- `invalid_file_name:*` - basename is not `^[a-z0-9_]+$`
- `invalid_json:*` - malformed JSON
- `duplicate_role_name_casefold:*` - duplicate by case-fold
- `role_name_mismatch:*` - internal `role_name` differs from basename

## Duplicate Handling
If two files collide by case-fold, first file in stable sorted order wins, others are ignored with errors.

## Runtime/UI Usage
- `/roles` and role callbacks reload files on every request.
- Valid roles are shown even when some files are invalid.
- Errors are displayed in UI and logged.

## Deactivation Behavior
If a role file is removed or renamed:
- its previous team bindings are deactivated automatically,
- no automatic rebinding to a new file name is performed.

## Agent Checklist Before Writing
1. Choose a valid lowercase underscore basename.
2. Write valid JSON object.
3. Ensure `base_system_prompt` exists (or alias form).
4. Prefer canonical keys even if aliases are supported.
5. Avoid creating case-fold duplicates.
