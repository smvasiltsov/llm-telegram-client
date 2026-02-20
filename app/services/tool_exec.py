from __future__ import annotations

import logging
from typing import Any

from app.storage import Storage
from app.tools import ToolAuthRequiredError, ToolContext, ToolService, ToolTimeoutError, ToolValidationError
from app.utils import split_message

logger = logging.getLogger("bot")


def _render_bash_result(cmd: str, result: Any) -> str:
    duration_ms = result.meta.get("duration_ms")
    role = result.meta.get("role")
    cwd = result.meta.get("cwd")
    lines = [
        f"$ {cmd}",
        f"role: {role}",
        f"cwd: {cwd}",
        f"exit_code: {result.exit_code}",
        f"duration_ms: {duration_ms}",
    ]
    if result.meta.get("truncated_stdout"):
        lines.append("stdout: truncated")
    if result.meta.get("truncated_stderr"):
        lines.append("stderr: truncated")
    header = "\n".join(lines).strip()
    stdout = result.stdout.strip() or "<empty>"
    stderr = result.stderr.strip()
    body = f"{header}\n\nSTDOUT:\n{stdout}"
    if stderr:
        body = f"{body}\n\nSTDERR:\n{stderr}"
    return body


async def execute_bash_command(
    *,
    cmd: str,
    caller_id: int,
    chat_id: int,
    message_id: int,
    trusted: bool,
    tool_service: ToolService,
    storage: Storage,
    bash_cwd_by_user: dict[int, str],
    bot: Any,
) -> bool:
    tool_ctx = ToolContext(
        caller_id=caller_id,
        chat_id=chat_id,
        source="telegram",
        request_id=f"tg:{chat_id}:{message_id}",
    )
    tool_input: dict[str, Any] = {"cmd": cmd, "trusted": trusted}
    current_cwd = bash_cwd_by_user.get(caller_id)
    if current_cwd:
        tool_input["cwd"] = current_cwd
    try:
        result = await tool_service.execute("bash", tool_input, tool_ctx)
    except ToolAuthRequiredError:
        storage.log_tool_run(
            telegram_user_id=caller_id,
            chat_id=chat_id,
            source="telegram",
            tool_name="bash",
            command_text=cmd,
            role="privileged",
            requires_password=True,
            trusted=trusted,
            status="auth_required",
        )
        return False
    except ToolValidationError as exc:
        storage.log_tool_run(
            telegram_user_id=caller_id,
            chat_id=chat_id,
            source="telegram",
            tool_name="bash",
            command_text=cmd,
            role=None,
            requires_password=False,
            trusted=trusted,
            status="validation_error",
            error_text=str(exc),
        )
        await bot.send_message(chat_id=chat_id, text=f"Ошибка в параметрах: {exc}")
        return True
    except ToolTimeoutError as exc:
        storage.log_tool_run(
            telegram_user_id=caller_id,
            chat_id=chat_id,
            source="telegram",
            tool_name="bash",
            command_text=cmd,
            role=None,
            requires_password=False,
            trusted=trusted,
            status="timeout",
            error_text=str(exc),
        )
        await bot.send_message(chat_id=chat_id, text=f"Таймаут: {exc}")
        return True
    except Exception:
        storage.log_tool_run(
            telegram_user_id=caller_id,
            chat_id=chat_id,
            source="telegram",
            tool_name="bash",
            command_text=cmd,
            role=None,
            requires_password=False,
            trusted=trusted,
            status="error",
            error_text="unexpected_error",
        )
        logger.exception("bash tool failed")
        await bot.send_message(chat_id=chat_id, text="Ошибка выполнения команды.")
        return True

    result_cwd = result.meta.get("cwd")
    if isinstance(result_cwd, str) and result_cwd.strip():
        bash_cwd_by_user[caller_id] = result_cwd

    body = _render_bash_result(cmd, result)
    storage.log_tool_run(
        telegram_user_id=caller_id,
        chat_id=chat_id,
        source="telegram",
        tool_name="bash",
        command_text=cmd,
        role=str(result.meta.get("role") or ""),
        requires_password=bool(result.meta.get("requires_password", False)),
        trusted=trusted,
        status="ok" if result.ok else "non_zero_exit",
        exit_code=result.exit_code,
        duration_ms=int(result.meta.get("duration_ms", 0)),
    )
    for chunk in split_message(body):
        await bot.send_message(chat_id=chat_id, text=chunk)
    return True
