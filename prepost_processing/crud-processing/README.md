# crud-processing

## Назначение
`crud-processing` выполняет безопасные файловые операции только внутри `root_dir`.

## Операции
- `create`: создать файл.
- `update`: перезаписать файл.
- `delete`: удалить файл/пустую директорию (или рекурсивно).
- `read`: прочитать файл с лимитом.
- `list`: получить список элементов директории.
- `diff_apply`: применить single-file unified diff к файлу в `root_dir`.

## Конфиг
Поддерживается merge: `config.json` (дефолты) + входной `payload.config` (override).

Поля:
- `root_dir` (обязательно): существующая директория-граница.
- `max_content_bytes` (опц., default из `config.json`): лимит размера контента.
- `max_list_entries` (опц., default из `config.json`): лимит выдачи `list`.
- `max_diff_bytes` (опц.): максимальный размер `diff_text` в байтах.
- `max_diff_lines` (опц.): максимальное число строк в `diff_text`.
- `allowed_diff_modes` (опц.): разрешенные режимы для `diff_apply` (`strict`, `autofix`).

## Формат payload
Вызов через envelope:
- `phase`: `pre|post`
- `config`: конфиг скилла
- `data`: операция

Пример `data`:
```json
{
  "operation": "create",
  "path": "docs/note.txt",
  "content": "hello",
  "create_parents": true
}
```

Пример `data` для `diff_apply`:
```json
{
  "operation": "diff_apply",
  "path": "docs/a.txt",
  "mode": "strict",
  "dry_run": true,
  "expected_sha256": "optional_sha256_hex",
  "diff_text": "--- a/docs/a.txt\n+++ b/docs/a.txt\n@@ -1 +1 @@\n-old\n+new\n"
}
```

## Примеры вызовов
```bash
python3 scripts/prepost_processing_runner.py \
  --prepost-processing-id crud-processing \
  --phase pre \
  --payload-json '{"operation":"list","path":"."}' \
  --config-json '{"root_dir":"/tmp/safe-root"}'
```

```bash
python3 scripts/prepost_processing_runner.py \
  --prepost-processing-id crud-processing \
  --phase pre \
  --payload-json '{"operation":"create","path":"a.txt","content":"x"}' \
  --config-json '{"root_dir":"/tmp/safe-root"}'
```

```bash
python3 scripts/prepost_processing_runner.py \
  --prepost-processing-id crud-processing \
  --phase pre \
  --payload-json '{"operation":"diff_apply","path":"docs/a.txt","mode":"strict","dry_run":true,"diff_text":"--- a/docs/a.txt\n+++ b/docs/a.txt\n@@ -1 +1 @@\n-old\n+new\n"}' \
  --config-json '{"root_dir":"/tmp/safe-root"}'
```

## Ошибки и ограничения
`PrePostProcessingResult.status`:
- `ok`: операция выполнена.
- `error`: ошибка выполнения.

Типовые `error`:
- `root_dir is required...`
- `path traversal is not allowed`
- `path escapes root_dir`
- `unsupported operation`
- `content exceeds max_content_bytes`
- `diff source header path must match payload.path`
- `diff_text exceeds max_diff_bytes`
- `diff_text exceeds max_diff_lines`
- `expected_sha256 mismatch`
- `hunk ... mismatch`

Ограничения безопасности:
- абсолютные пути запрещены;
- попытки выхода за `root_dir` блокируются;
- удаление самого `root_dir` запрещено.
- `diff_apply` поддерживает только single-file unified diff;
- `diff`-headers должны указывать тот же `payload.path` (без выхода за root);
- запись при `diff_apply` выполняется атомарно (`temp file + replace`);
- `mode=autofix` делает только безопасные правки: `CRLF -> LF` и нормализацию `\ No newline at end of file`;
- `mode=autofix` не исправляет target path и не делает «умных» догадок по контексту.
