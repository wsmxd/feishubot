from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from feishubot.ai.tools.base import Tool


class TerminalCommandTool(Tool):
    name = "terminal"
    description = (
        "Execute a shell command and return stdout, stderr, exit code, and timeout status."
    )

    _DANGEROUS_COMMAND_PATTERNS: tuple[str, ...] = (
        r"(^|\s)rm\s+-rf\s+/",
        r"(^|\s)(reboot|shutdown|halt|poweroff)(\s|$)",
        r"(^|\s)mkfs(\.|\s|$)",
        r"(^|\s)dd\s+if=",
        r"\bcurl\b[^\n|;]*\|[^\n]*\b(sh|bash|zsh)\b",
        r"\bwget\b[^\n|;]*\|[^\n]*\b(sh|bash|zsh)\b",
        r":\(\)\s*\{\s*:\|:\s*&\s*\};:",
    )

    @classmethod
    def _validate_command(cls, command: str, *, allow_dangerous: bool) -> None:
        if not command:
            raise ValueError("terminal requires a 'command' argument")
        if len(command) > 4000:
            raise ValueError("command too long")
        if allow_dangerous:
            return

        lowered = command.lower()
        for pattern in cls._DANGEROUS_COMMAND_PATTERNS:
            if re.search(pattern, lowered):
                raise ValueError("command blocked by safety policy")

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = str(arguments.get("command", "")).strip()
        allow_dangerous = bool(arguments.get("allow_dangerous", False))
        self._validate_command(command, allow_dangerous=allow_dangerous)

        cwd_value = arguments.get("cwd")
        cwd_path = None
        if cwd_value:
            cwd_path = Path(str(cwd_value)).expanduser().resolve()
            if not cwd_path.exists():
                raise ValueError(f"cwd does not exist: {cwd_path}")

        timeout_seconds_raw = arguments.get("timeout_seconds", 60)
        try:
            timeout_seconds = float(timeout_seconds_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_seconds must be numeric") from exc
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")

        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd_path) if cwd_path is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds
            )
        except TimeoutError:
            timed_out = True
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()

        stdout = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""

        return {
            "command": command,
            "cwd": str(cwd_path) if cwd_path is not None else None,
            "timeout_seconds": timeout_seconds,
            "timed_out": timed_out,
            "exit_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
