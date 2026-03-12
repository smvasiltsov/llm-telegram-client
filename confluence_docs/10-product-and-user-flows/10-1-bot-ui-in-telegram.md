---
title: 10.1 Bot UI in Telegram
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5439508
  parent_doc_path: 10-product-and-user-flows/_index.md
  local_id: 10-1-bot-ui-in-telegram
  parent_local_id: 10-product-and-user-flows
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 10.1 Bot UI in Telegram

## Entry Points
LTC is managed through Telegram itself and exposes two interaction surfaces:
- group chats for role-based AI conversations,
- private chat with the bot for configuration.

The primary command for configuration is `/groups` in private chat.

## Group Chat Experience
In a group, the user sends a message and mentions a role (for example, `@analyst`).
Depending on routing configuration, a bot mention may also be required.

Expected behavior:
- role mention triggers role-specific processing,
- the selected role controls model and prompt settings,
- response is posted back to the same group thread.

## Private Configuration UI
The private UI is navigation-driven and centered on groups and roles:
- open `/groups`,
- select target group,
- open role card,
- adjust role settings.

Role card actions include:
- system prompt,
- general message instructions,
- reply-context instructions,
- LLM model selection,
- rename role,
- reset role session,
- delete role,
- manage skills,
- manage pre/post processing.

## Skills and Pre/Post Sections in UI
The UI keeps two separate concepts:
- **Skills**: model-callable capabilities enabled per role.
- **Pre/Post Processing**: automatic server-side hooks around LLM calls.

This separation helps users reason about what the model can invoke directly versus what always executes in the pipeline.

## Response Formatting in Telegram
Output rendering follows configured formatting mode (`markdown` or `html`).
When raw HTML mode is enabled and Telegram rejects markup, the bot falls back to safe escaped output.

## UX Guardrails
- Commands are intended for private chat.
- Group interaction is kept lightweight: users invoke roles, while configuration stays in private UI.
- Sensitive provider fields are requested interactively when required.
