---
title: 30.5 Plugins and Post-processing
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5111829
  parent_doc_path: 30-llm-integration/_index.md
  local_id: 30-5-plugins-and-post-processing
  parent_local_id: 30-llm-integration
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 30.5 Plugins and Post-processing

## Two Post-LLM Extension Paths
LTC supports two complementary mechanisms after LLM output:
- plugin-based output customization,
- pre/post processing pipeline configured per role.

They serve different purposes and can coexist.

## Plugins
Plugins are Python modules under `plugins/` that implement declared hooks (notably `on_llm_response`).
A plugin can:
- modify response text,
- modify parse mode,
- attach reply markup.

Example use case in LTC: long-response handling with a button that opens full content.

## Plugin Configuration
Each plugin can have JSON config in `plugins/<id>.json`, including enable flag and feature-specific parameters.
When disabled, plugin logic is bypassed.

## Plugin Delivery Details
When plugin output requests a web app button:
- private chats can use WebApp buttons,
- group chats use URL buttons.

LTC validates button payload before sending to prevent malformed output.

## Pre/Post Processing Hooks
Pre/post processing modules run around LLM execution as server-side transformations.
Typical responsibilities:
- input normalization before provider call,
- output normalization after provider response,
- role-specific automated adjustments.

## Configuration Scope
Both plugins and pre/post processors are applied with explicit runtime configuration:
- plugins are globally available with per-plugin config,
- pre/post processors are enabled per role/group binding.

## Operational Notes
- Keep transformation logic deterministic and observable.
- Avoid duplicating responsibilities across plugins and pre/post processors.
- Use role-scoped enablement to limit side effects.
