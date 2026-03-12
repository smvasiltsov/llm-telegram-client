# Publish Checklist

1. У каждого `.md` есть front matter с `title` и `sync.mode: publish`.
2. `confluence.local_id` уникален во всем `confluence_docs/`.
3. Для дочерних страниц задан `parent_local_id` или `parent_doc_path` (или корректная папочная иерархия).
4. В MCP-вызове передан `space_id`.
5. Если нужна публикация под конкретный узел, передан `root_page_id`.
6. Сначала выполнен `mode: dry-run`, нет критичных `errors`.
7. Для записи реальных ID включен `rewrite_frontmatter_ids: true`.
8. После `apply` проверены `created/updated/skipped/errors/warnings`.
9. Изменения front matter и `.confluence-publish/state.json` добавлены в commit.
