# Skills Dev Guide (Iteration 1)

## Quick Start
1. Create folder:
   - `skills/<skill_id>/`
2. Add:
   - `skill.yaml`
   - `skill.py`
3. Implement contract:
   - `describe()`
   - `validate_config(config)`
   - `run(ctx, payload)`

Use `skills/_template` as baseline.

## Local Runner
Run skill outside bot:

```bash
python3 scripts/skill_runner.py \
  --skill-id echo \
  --phase pre \
  --payload-json '{"user_text":"hello","reply_text":null}' \
  --config-json '{}'
```

With files:

```bash
python3 scripts/skill_runner.py \
  --skill-id echo \
  --phase post \
  --payload-file skills/echo/mocks/payload.json \
  --config-file skills/echo/mocks/config.json
```

## Payload Envelope
Runner and bot call skill with:
- `phase`: `pre` or `post`
- `config`: role-skill config
- `data`: payload data

Supported output overrides:
- `pre`:
  - `output.user_text`
  - `output.reply_text`
- `post`:
  - `output.response_text`

## Guardrails
- Timeout per skill from manifest (`timeout_sec`, clamped).
- Output size limit applied in bot runtime.
- Unsupported permissions lead to skill skip.
