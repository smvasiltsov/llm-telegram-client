# Quickstart (Isolated Skills Repo)

## Create new skill
1. Copy `skills/_template` to `skills/<new_id>`.
2. Update `skills/<new_id>/skill.yaml`:
   - `id`
   - `version`
   - `entrypoint`
3. Implement logic in `skills/<new_id>/skill.py`.

## Local run
```bash
python3 scripts/skill_runner.py --skill-id <new_id> --phase pre --payload-json '{"user_text":"ping"}'
```

## Local tests
```bash
python3 -m unittest discover -s tests -v
```

## Publish into bot repository
```bash
scripts/publish_to_bot_skills.sh --bot-repo /path/to/bot --skill-id <new_id>
```
