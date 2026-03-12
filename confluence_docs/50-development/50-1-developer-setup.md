---
title: 50.1 Developer Setup
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5898260
  parent_doc_path: 50-development/_index.md
  local_id: 50-1-developer-setup
  parent_local_id: 50-development
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 50.1 Developer Setup

## Prerequisites
- Python 3.9+
- Telegram bot token from BotFather
- Access to at least one configured LLM provider endpoint

## Environment Setup
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Configuration Bootstrap
1. Copy template config:
```bash
cp config.example.json config.json
```
2. Fill required values in `config.json`:
- `telegram_bot_token`
- `database_path`
- `encryption_key`
- `owner_user_id`
- provider/runtime options as needed.

## Cryptographic Key
Generate `encryption_key` value:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Provider Readiness
Ensure `llm_providers/` contains valid provider JSON files before startup.
Without valid providers, model selection and execution paths will fail.

## Startup
Run the bot:
```bash
python bot.py
```

## First Functional Check
- Open private chat and run `/groups`.
- Select target group.
- Create/select a role and set model.
- Send a group request with role mention.

## Development Notes
- Keep `.env` and secret values local.
- Prefer changing provider behavior through JSON configs, not code patches, when possible.
- Restart bot after config/schema-impacting changes.
