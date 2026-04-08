from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from feishubot.ai.tools.base import Tool


class TerminalCommandTool(Tool):
    name = "terminal"
    description = (
        "Execute a shell command and return stdout, stderr, exit code, and timeout status."
    )

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        command = str(arguments.get("command", "")).strip()
        if not command:
            raise ValueError("terminal requires a 'command' argument")

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
