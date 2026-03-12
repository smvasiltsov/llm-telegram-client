# Quick Start

This repository is for building model-callable `skills` without any dependency on the real Telegram bot runtime or on a real LLM provider.

## Setup

1. Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run smoke tests:

```bash
python3 -m unittest discover -s tests -v
```

3. Run the example skill locally:

```bash
python3 scripts/skill_runner.py \
  --skills-dir skills \
  --skill-id echo.skill \
  --arguments-json '{"message":"hello"}' \
  --config-json '{}'
```

4. Run the real filesystem example locally:

```bash
mkdir -p sandbox
printf 'abcdefghij' > sandbox/sample.txt
python3 scripts/skill_runner.py \
  --skills-dir skills \
  --skill-id fs.read_file \
  --arguments-json '{"path":"sample.txt","start_char":2,"end_char":6}' \
  --config-json '{"root_dir":"./sandbox"}'
```

5. Preview what LLM will see for enabled skills and contracts:

```bash
python3 scripts/skills_prompt_preview.py \
  --skills-dir skills \
  --enabled-skill-id fs.read_file \
  --enabled-skill-id fs.write_file \
  --output input_json_compact
```

По умолчанию в preview уже включены debug-метаданные навыка:
- `version`, `timeout_sec`, `permissions`
- `manifest.id/version/entrypoint`
- `config_contract_hints.validate_config_errors_for_empty_config`

Если нужен excerpt из README навыка:

```bash
python3 scripts/skills_prompt_preview.py \
  --skills-dir skills \
  --enabled-skill-id fs.read_file \
  --include-readme \
  --readme-max-chars 1500 \
  --output skills_only
```

## Create a new skill

1. Copy `skills/_template` to `skills/<your_skill_folder>`
2. Update `skill.yaml`
3. Implement `skill.py`
4. Test locally with `scripts/skill_runner.py`
5. Run `python3 -m unittest discover -s tests -v`
