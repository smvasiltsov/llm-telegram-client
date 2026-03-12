# Confluence Auto Sync Kit

Готовый набор для быстрого старта:

- `templates/` — copy-paste шаблоны front matter и markdown-страниц.
- `test-pages/` — тестовая структура `confluence_docs` для первого прогона.
- `CHECKLIST.md` — короткий чеклист перед `mcp_publish`.

Рекомендуемый порядок:

1. Скопировать `test-pages/` в рабочую папку `confluence_docs/` в репозитории.
2. Проверить `local_id` и связи родителей.
3. Выполнить `dry-run`.
4. Выполнить `apply` с `rewrite_frontmatter_ids=true`.
