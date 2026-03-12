---
title: 50.3 Adding New Provider
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5898279
  parent_doc_path: 50-development/_index.md
  local_id: 50-3-adding-new-provider
  parent_local_id: 50-development
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 50.3 Adding New Provider

## Overview
Adding a provider in LTC is primarily a configuration task. Providers are discovered from JSON files in `llm_providers/`.

## Steps
1. Create a new JSON file in `llm_providers/`.
2. Define required metadata:
- `id`, `label`, `base_url`, `adapter`.
3. Set capability flags to match real API support.
4. Define endpoint contracts (`send_message` required; others optional).
5. Add `models` list.
6. Add `user_fields` if provider requires runtime values.
7. Configure `history` behavior.
8. Restart bot and verify provider appears in runtime logs/UI.

## Minimum Required Contract
Provider config must correctly define:
- request template for message send,
- response extraction path (or stream mapping),
- valid model identifiers.

## Validation Checklist
- JSON parses successfully.
- Provider id is unique.
- Endpoint paths/methods match remote API.
- Placeholder keys map to runtime values.
- Required user fields are collectable in private flow.

## Runtime Verification
- Create/select role.
- Assign model from new provider.
- Send test prompt in group.
- Confirm response returns and history behavior matches provider config.

## Common Failure Sources
- wrong `base_url`,
- invalid response path,
- missing capability alignment,
- missing required user field values.
