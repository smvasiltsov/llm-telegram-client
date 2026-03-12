---
title: 70.2 ADR-002 Event-Driven Processing for Telegram Updates
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 6193153
  parent_doc_path: 70-decisions-adr/_index.md
  local_id: 70-2-adr-002-event-driven-processing-for-telegram-updates
  parent_local_id: 70-decisions-adr
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 70.2 ADR-002 Event-Driven Processing for Telegram Updates

## Status
Accepted

## Context
LTC receives heterogeneous Telegram events:
- private messages,
- group messages,
- callback interactions,
- membership changes.

The system needs predictable routing, role-aware context handling, optional skill execution, and resilient output delivery.

A monolithic request handler would mix transport, orchestration, and business logic, reducing maintainability and increasing operational risk.

## Decision
Adopt an event-driven processing model with layered handlers and service orchestration:

1. Transport handlers classify update type and entry path.
2. Role/group context is resolved before LLM execution.
3. Prompt assembly and policy checks run in service layer.
4. Optional pre-processing hooks run before model call.
5. LLM execution runs directly or through skill-calling loop.
6. Optional post-processing hooks run after model output.
7. Formatting and delivery are handled by dedicated output services.

## Decision Drivers
- Clear separation of concerns.
- Runtime extensibility (skills, tools, plugins, processors).
- Safer error handling per stage.
- Better observability and debugging.

## Consequences

### Positive
- Easier evolution of individual pipeline stages.
- Deterministic flow boundaries between private and group behavior.
- Structured control points for security and capability checks.
- Better diagnostics via stage-oriented logs and storage records.

### Trade-offs
- More components to wire and maintain.
- Requires strict contracts between handlers and services.
- Increased need for integration tests across stage boundaries.

## Rejected Alternatives
- Single unified handler with inline provider/tool logic.
- Direct LLM calls inside Telegram handlers without staged services.

Both alternatives were rejected due to maintainability and operational complexity risks.

## Implementation Notes
This decision is reflected in:
- `app/handlers/*` for transport routing,
- `app/services/*` for orchestration/prompt/loop/output,
- `app/runtime.py` for dependency composition,
- role-scoped persistence and capability tables in SQLite.
