# Skills Runner

Скрипт для прямого вызова model-callable `skills` из терминала без Telegram, UI и LLM.

Файл:

- `scripts/skills_runner.py`

## Что делает

- Загружает навыки через `app.skills.SkillRegistry`.
- Показывает полный список обнаруженных навыков с контрактами (`input_schema`).
- Выполняет конкретный навык с mock-контекстом (`chat_id`, `user_id`, `role_id`, `role_name`).

## Команды

### 1) Список навыков

```bash
python3 scripts/skills_runner.py \
  --skills-dir skills \
  list
```

Опционально можно отфильтровать один навык:

```bash
python3 scripts/skills_runner.py \
  --skills-dir skills \
  list \
  --skill-id fs.read_file
```

### 2) Выполнить навык

```bash
python3 scripts/skills_runner.py \
  --skills-dir skills \
  exec \
  --skill-id fs.list_dir \
  --arguments-json '{"path":"."}' \
  --config-json '{"root_dir":"/tmp"}'
```

## Передача аргументов и конфига

- inline JSON:
  - `--arguments-json '{"path":"README.md"}'`
  - `--config-json '{"root_dir":"/tmp"}'`
- JSON file:
  - `--arguments-file ./examples/args.json`
  - `--config-file ./examples/config.json`

Если указаны и файл, и inline JSON, значения из inline JSON перекрывают значения из файла.

## Коды выхода

- `0`: успешно
- `1`: ошибка валидации входного JSON / аргументов CLI
- `2`: навык не найден
- `3`: `validate_config(...)` вернул ошибки
