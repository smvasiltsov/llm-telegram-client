from __future__ import annotations

import asyncio
import shlex
import time
from pathlib import Path
from typing import Any

from app.tools.base import ToolContext, ToolResult
from app.tools.errors import ToolAuthRequiredError, ToolTimeoutError, ToolValidationError


class BashTool:
    def __init__(
        self,
        default_cwd: Path,
        max_timeout_sec: int = 30,
        max_output_chars: int = 12_000,
        safe_commands: list[str] | None = None,
        allowed_workdirs: list[Path] | None = None,
    ) -> None:
        self._default_cwd = default_cwd.resolve()
        self._max_timeout_sec = max_timeout_sec
        self._max_output_chars = max_output_chars
        self._safe_commands = {cmd.strip().lower() for cmd in (safe_commands or []) if cmd.strip()}
        workdirs = allowed_workdirs or [self._default_cwd]
        self._allowed_workdirs = [path.resolve() for path in workdirs]

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "Run a bash command and return stdout/stderr with exit code"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["cmd"],
            "properties": {
                "cmd": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_sec": {"type": "integer", "minimum": 1, "maximum": self._max_timeout_sec},
                "trusted": {"type": "boolean"},
            },
        }

    async def execute(self, tool_input: dict[str, Any], ctx: ToolContext) -> ToolResult:
        cmd = str(tool_input.get("cmd", "")).strip()
        if not cmd:
            raise ToolValidationError("Field 'cmd' cannot be empty")
        trusted = bool(tool_input.get("trusted", False))
        security = self.command_security(cmd)
        if security["requires_password"] and not trusted:
            raise ToolAuthRequiredError("Password confirmation is required for this command")

        cwd_raw = tool_input.get("cwd")
        cwd = self._resolve_cwd(cwd_raw)
        timeout = self._resolve_timeout(tool_input.get("timeout_sec"), ctx.timeout_sec)
        args = self._parse_args(cmd)
        if args and Path(args[0]).name.lower() == "cd":
            target_cwd = self._resolve_cd_target(cwd, args)
            return ToolResult(
                ok=True,
                stdout="",
                stderr="",
                exit_code=0,
                meta={
                    "duration_ms": 0,
                    "cwd": str(target_cwd),
                    "timeout_sec": timeout,
                    "truncated_stdout": False,
                    "truncated_stderr": False,
                    "role": security["role"],
                    "requires_password": security["requires_password"],
                    "executable": security["executable"],
                    "cwd_changed": True,
                },
            )

        started = time.monotonic()
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.communicate()
            raise ToolTimeoutError(f"Command timed out after {timeout}s") from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        stdout, out_truncated = self._truncate(stdout)
        stderr, err_truncated = self._truncate(stderr)

        return ToolResult(
            ok=(proc.returncode == 0),
            stdout=stdout,
            stderr=stderr,
            exit_code=int(proc.returncode or 0),
            meta={
                "duration_ms": duration_ms,
                "cwd": str(cwd),
                "timeout_sec": timeout,
                "truncated_stdout": out_truncated,
                "truncated_stderr": err_truncated,
                "role": security["role"],
                "requires_password": security["requires_password"],
                "executable": security["executable"],
                "cwd_changed": False,
            },
        )

    def _resolve_cwd(self, cwd_raw: Any) -> Path:
        if cwd_raw is None:
            return self._default_cwd
        value = str(cwd_raw).strip()
        if not value:
            return self._default_cwd
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = (self._default_cwd / path).resolve()
        else:
            path = path.resolve()
        if not path.exists() or not path.is_dir():
            raise ToolValidationError(f"Working directory not found: {path}")
        if not any(self._is_within(path, base) for base in self._allowed_workdirs):
            raise ToolValidationError(f"Working directory is not allowed: {path}")
        return path

    def command_security(self, cmd: str) -> dict[str, Any]:
        try:
            args = shlex.split(cmd, posix=True)
        except ValueError:
            return {
                "role": "privileged",
                "requires_password": True,
                "reason": "unparsable",
                "executable": "",
            }
        if not args:
            raise ToolValidationError("Command is empty")
        executable = args[0]
        executable_name = Path(executable).name.lower()
        is_safe = executable_name in self._safe_commands
        if is_safe:
            return {
                "role": "safe",
                "requires_password": False,
                "reason": "safe_command",
                "executable": executable_name,
            }
        return {
            "role": "privileged",
            "requires_password": True,
            "reason": "not_in_safe_list",
            "executable": executable_name,
        }

    def _resolve_timeout(self, input_timeout: Any, ctx_timeout: int | None) -> int:
        timeout_value = ctx_timeout if ctx_timeout is not None else input_timeout
        if timeout_value is None:
            return min(15, self._max_timeout_sec)
        try:
            timeout = int(timeout_value)
        except (TypeError, ValueError) as exc:
            raise ToolValidationError("timeout_sec must be an integer") from exc
        if timeout <= 0:
            raise ToolValidationError("timeout_sec must be > 0")
        if timeout > self._max_timeout_sec:
            raise ToolValidationError(f"timeout_sec cannot exceed {self._max_timeout_sec}")
        return timeout

    def _truncate(self, text: str) -> tuple[str, bool]:
        if len(text) <= self._max_output_chars:
            return text, False
        suffix = "\n...[truncated]"
        cut = max(0, self._max_output_chars - len(suffix))
        return text[:cut] + suffix, True

    def _parse_args(self, cmd: str) -> list[str]:
        try:
            return shlex.split(cmd, posix=True)
        except ValueError as exc:
            raise ToolValidationError(f"Invalid shell command: {exc}") from exc

    def _resolve_cd_target(self, cwd: Path, args: list[str]) -> Path:
        if len(args) > 2:
            raise ToolValidationError("cd supports only one target directory")
        raw_target = "~" if len(args) == 1 else args[1]
        target = Path(raw_target).expanduser()
        if not target.is_absolute():
            target = (cwd / target).resolve()
        else:
            target = target.resolve()
        if not target.exists() or not target.is_dir():
            raise ToolValidationError(f"Working directory not found: {target}")
        if not any(self._is_within(target, base) for base in self._allowed_workdirs):
            raise ToolValidationError(f"Working directory is not allowed: {target}")
        return target

    @staticmethod
    def _is_within(path: Path, base: Path) -> bool:
        if path == base:
            return True
        return base in path.parents
