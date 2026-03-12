---
title: 30.1 Providers Overview
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5701633
  parent_doc_path: 30-llm-integration/_index.md
  local_id: 30-1-providers-overview
  parent_local_id: 30-llm-integration
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 30.1 Providers Overview

## Provider Model in LTC
LTC integrates LLM backends through JSON provider definitions stored in `llm_providers/*.json`.
A provider file defines:
- API base URL,
- supported capabilities,
- endpoint contracts,
- optional user fields,
- model catalog,
- history behavior.

This design makes provider integration configuration-driven instead of hardcoded.

## Provider and Model Identifiers
- `provider_id`: unique provider key (for example `ollama`, `codex-api`).
- `model_id`: model key inside provider.
- Combined runtime key: `provider_id:model_id`.

The bot resolves provider and model from role settings and optional overrides.

## Capability Flags
Provider capabilities indicate which operations are supported:
- `list_sessions`
- `create_session`
- `rename_session`
- `model_select`

LTC checks capability flags before attempting an operation.
If a capability is disabled, the corresponding flow is skipped or rejected.

## Generic Adapter Contract
Current integrations use `adapter = generic` with declarative request/response mappings.
This supports both standard JSON response APIs and streaming providers.

## Runtime Selection Flow
1. Role provides selected model reference.
2. Router resolves provider/model pair.
3. Provider config is loaded from registry.
4. Request payload is rendered from endpoint templates.
5. Response is parsed according to configured response paths.

## Why This Matters
- New providers can be added without modifying core handler code.
- Runtime behavior remains explicit and traceable.
- Provider differences are isolated in config contracts.
