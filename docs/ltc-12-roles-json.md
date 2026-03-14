# LTC-12: Role JSON Catalog

## Scope
LTC-12 moves master-role configuration from database records to JSON files in `roles_catalog/`.

## Identity Rules
- Role identity is taken only from file name: `basename(.json)`.
- Valid basename pattern: `^[a-z0-9_]+$`.
- No auto-normalization is applied.
- `role_name` inside JSON is not used for identity (metadata only).

## Duplicate Rules
- Files are scanned in stable sorted order.
- Duplicate by case-fold (`Dev.json` vs `dev.json`) is resolved deterministically:
  - first discovered file wins,
  - other files are reported as catalog errors and not loaded.

## JSON Fields
Required:
- `base_system_prompt` (string), aliases: `system_prompt`, `prompt`

Optional:
- `description` (string), alias: `summary`, default: `""`
- `extra_instruction` (string), alias: `instruction`, default: `""`
- `llm_model` (string or null), alias: `model`, default: `null`
- `is_active` (bool), aliases: `active`, `enabled`, default: `true`
- `schema_version` (must be `1` if provided, default: `1`)
- `role_name` (string metadata only, mismatch is reported)

## Catalog Hot-Reload
- Catalog is reloaded from disk on every `/roles` request.
- Catalog is reloaded for `/roles` callbacks (`mroles` / `mrole*`).
- Runtime message flows also refresh catalog before role resolution.

## UI Behavior
- `/roles` shows valid roles and a separate list of catalog errors.
- `mroles:list` behaves the same.
- Role card and bind actions use current file-backed role state.

## Runtime Behavior
- Prompt/instruction/model defaults are taken from JSON master-role.
- Team overrides are applied on top of master defaults.
- Removed or renamed role files stop participating in routing after refresh.

## Binding Deactivation on Remove/Rename
On refresh, if active `team_roles.role_name` is absent in loaded catalog:
- related bindings are deactivated (`is_active=0`, `enabled=0`, `mode='normal'`).
- no auto-migration of bindings to a renamed file identity is performed.

## Migration and Compatibility Notes
- Existing DB-based roles can be exported to JSON on first run.
- Existing JSON files with mismatched internal `role_name` remain valid by filename identity.
- Mismatch is reported as warning/error in catalog issues for visibility.

## Known Limitations
- Case-fold duplicate winner depends on stable file sort order.
- Invalid basename files are ignored as role sources.
- Renaming a file changes identity; previous bindings are deactivated.
