from __future__ import annotations

from typing import Any


def human_issue_reason(reason: str) -> str:
    if reason.startswith("invalid_file_name:"):
        return "некорректное имя файла (разрешены только [a-z0-9_])"
    if reason.startswith("duplicate_role_name_casefold:"):
        winner = reason.split("winner=", 1)[1] if "winner=" in reason else "unknown"
        return f"дубликат имени роли по регистру; используется файл {winner}"
    if reason.startswith("role_name_mismatch:"):
        payload_name = reason.split(":", 1)[1].split("->", 1)[0]
        return f"role_name в JSON ({payload_name}) не совпадает с именем файла; используется имя файла"
    return reason


def master_roles_list_text(runtime: Any, *, max_issues: int = 10) -> str:
    lines = ["Выбери master-role:"]
    issues = runtime.role_catalog.issues
    if not issues:
        return "\n".join(lines)
    lines.append("")
    lines.append(f"Ошибки чтения JSON: {len(issues)}")
    for issue in issues[:max_issues]:
        lines.append(f"- {issue.path.name}: {human_issue_reason(issue.reason)}")
    if len(issues) > max_issues:
        lines.append(f"- ... и ещё {len(issues) - max_issues}")
    return "\n".join(lines)
