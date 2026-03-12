---
title: 40.5 MCP Tool Runner (CLI)
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5701652
  parent_doc_path: 40-skills-and-mcp-platform/_index.md
  local_id: 40-5-mcp-tool-runner-cli
  parent_local_id: 40-skills-and-mcp-platform
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 40.5 MCP Tool Runner (CLI)

## Purpose
`mcp_tool_runner.py` executes MCP tool adapter calls directly from terminal, bypassing Telegram and LLM.

File:
- `scripts/mcp_tool_runner.py`

## Runtime Behavior
The runner initializes tool runtime from `config.json` and exposes:
- tool listing (`list`),
- tool execution (`exec`).

Results are printed as JSON to stdout.

## Access Control
`ToolMCPAdapter` allows calls only when `caller_id == owner_user_id` from config.
If caller is not owner:
- tool list is empty,
- execution returns forbidden error.

## Commands

### List tools
```bash
python3 scripts/mcp_tool_runner.py list \
  --config config.json \
  --caller-id <owner_user_id>
```

### Execute tool
```bash
python3 scripts/mcp_tool_runner.py exec \
  --config config.json \
  --caller-id <owner_user_id> \
  --chat-id -1001 \
  --tool-name bash \
  --tool-input-json '{"cmd":"pwd"}'
```

## Input Options
Tool input can be provided via:
- inline JSON (`--tool-input-json`),
- JSON file (`--tool-input-file`).

Inline JSON overrides file values.

## Output Focus Fields
Execution output typically includes:
- `ok`,
- `exit_code`,
- `stdout`, `stderr`,
- `meta` (cwd, timeout, duration, truncation flags, role metadata).

## Operational Limits
Runtime respects the same policy constraints as bot execution:
- tool enable flags,
- safe command policy,
- allowed working directories,
- timeout/output bounds.
