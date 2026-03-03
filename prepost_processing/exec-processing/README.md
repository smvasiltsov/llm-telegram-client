# exec-processing

## Назначение
`exec-processing` запускает только whitelisted команды внутри `root_dir`.

## Команды
Поддерживается операция:
- `exec`: запуск `[command, *args]` через `subprocess.run(..., shell=False)`.

## Конфиг
Поддерживается merge: `config.json` (дефолты) + входной `payload.config` (override).

Поля:
- `root_dir` (обязательно): существующая директория-граница.
- `allowed_commands` (обязательно): whitelist команд, например `["echo"]`.
- `max_output_chars` (опц.): лимит `stdout`/`stderr`.
- `default_timeout_sec` (опц.): timeout по умолчанию.
- `max_args` (опц.): максимум аргументов.

## Формат payload
Envelope:
- `phase`: `pre|post`
- `config`: конфиг скилла
- `data`: операция

Пример `data`:
```json
{
  "operation": "exec",
  "command": "echo",
  "args": ["hello"],
  "cwd": ".",
  "timeout_sec": 3
}
```

## Примеры вызовов
```bash
python3 scripts/prepost_processing_runner.py \
  --prepost-processing-id exec-processing \
  --phase pre \
  --payload-json '{"operation":"exec","command":"echo","args":["ping"]}' \
  --config-json '{"root_dir":"/tmp/safe-root","allowed_commands":["echo"]}'
```

## Ошибки и ограничения
`PrePostProcessingResult.status`:
- `ok`: команда выполнена.
- `error`: ошибка выполнения.

Типовые `error`:
- `allowed_commands is required...`
- `command is not allowed`
- `cwd traversal is not allowed`
- `cwd escapes root_dir`
- `command timed out`

Ограничения безопасности:
- `shell=False` всегда;
- только whitelist команд;
- `cwd` только relative и внутри `root_dir`;
- аргументы проходят ограничение по безопасному шаблону.
