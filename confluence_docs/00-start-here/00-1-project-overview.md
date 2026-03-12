---
title: 00.1 Project Overview
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5079042
  parent_doc_path: 00-start-here/_index.md
  local_id: 00-1-project-overview
  parent_local_id: 00-start-here
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 00.1 Project Overview

## What LTC Is
LTC (LLM-Telegram-Client) is a Telegram bot project that connects group conversations to LLM backends. It is designed for role-based interaction, where users mention a role in a group chat and receive an AI response generated through the configured provider and model.

## Core Product Behavior
- The bot is owner-scoped: it responds only to the configured owner user.
- Roles are configured per group and define prompts, instructions, and selected model.
- Each conversation session is isolated by user, group, and role.
- Provider definitions are file-based (`llm_providers/*.json`), so adding a provider is configuration-driven.
- The bot supports model-callable skills and pre/post processing pipelines around LLM calls.

## High-Level Architecture
The system is organized into clear layers:
- `app/handlers` for Telegram transport and interaction handling.
- `app/services` for reusable business logic (prompt building, formatting, skill loop, tool execution).
- `app/skills` for model-callable skills runtime and registry.
- `app/prepost_processing` for pre and post transformation hooks.
- `app/storage.py` and `app/models.py` for SQLite-backed persistence.

## Runtime Flow Summary
1. A group message is routed to a role.
2. Prompt is assembled from role settings, optional instructions, and context.
3. Pre-processing stages run.
4. LLM request executes directly or through a skill-calling loop.
5. Post-processing stages run.
6. Final response is sent back to Telegram.

## Key Stored Data
The SQLite database stores:
- groups and roles,
- role/group overrides,
- sessions and message history,
- user fields,
- enabled role skills,
- skill run logs,
- role pre/post processing bindings.

## Intended Audience
This documentation supports:
- product and operations stakeholders who need behavior and process visibility,
- developers who maintain runtime logic and integrations,
- AI agents that require concise, structured project context.
