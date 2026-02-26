# Publish Workflow To Bot

## Manual
1. Create or update skill in this repository under `skills/<id>/`.
2. Run local checks via runner/tests.
3. Copy `skills/<id>/` into bot repository `skills/<id>/`.
4. Restart bot process so discovery runs again.

## Scripted
Run:

```bash
scripts/publish_to_bot_skills.sh --bot-repo /path/to/bot --skill-id <id>
```

This copies one skill folder into `<bot-repo>/skills/<id>`.
