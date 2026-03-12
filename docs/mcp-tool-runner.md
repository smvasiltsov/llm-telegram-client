# MCP Tool Runner

Скрипт для прямого вызова MCP tool adapter из терминала без Telegram и LLM.

Файл:

- `scripts/mcp_tool_runner.py`

## Что делает

- Инициализирует tool runtime по `config.json` (`tools.bash.*`).
- Вызывает `ToolMCPAdapter.list_tools(...)` и `ToolMCPAdapter.execute_tool(...)`.
- Возвращает JSON результат в stdout.

## Важно про доступ

`ToolMCPAdapter` разрешает выполнение только если:

- `caller_id == owner_user_id` из `config.json`.

Иначе:

- `list` вернет пустой список;
- `exec` вернет `{"ok": false, "error": "forbidden"}`.

## Команды

Флаги верхнего уровня (`--config`, `--dotenv`) указываются **до** подкоманды (`list`/`exec`).

### 1) Список доступных инструментов

```bash
python3 scripts/mcp_tool_runner.py list \
  --config config.json \
  --caller-id 1234567890
```

### 2) Выполнить tool-вызов

```bash
python3 scripts/mcp_tool_runner.py exec \
  --config config.json \
  --caller-id 1234567890 \
  --chat-id -1001 \
  --tool-name bash \
  --tool-input-json '{"cmd":"pwd"}'
```

## Способы передать tool input

- inline JSON:
  - `--tool-input-json '{"cmd":"ls -la"}'`
- JSON file:
  - `--tool-input-file ./examples/bash_input.json`

Если указаны оба, значения из `--tool-input-json` перекрывают значения из файла.

## Полезные поля в результате

- `result.ok`
- `result.exit_code`
- `result.stdout`
- `result.stderr`
- `result.meta`

Для `bash` в `meta` обычно есть:

- `cwd`
- `timeout_sec`
- `duration_ms`
- `truncated_stdout`
- `truncated_stderr`
- `role`
- `requires_password`

## Ограничения

- Скрипт использует те же runtime-ограничения, что и бот (`safe_commands`, `allowed_workdirs`, timeout).
- Если `tools.enabled=false` или `tools.bash.enabled=false`, список будет пустым.
