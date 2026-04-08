from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from feishubot.ai.core.errors import ToolNotFoundError
from feishubot.ai.tools.base import Tool
from feishubot.ai.tools.builtins import register_builtin_tools
from feishubot.ai.tools.registry import tool_registry


@dataclass(slots=True)
class ToolInvocation:
    name: str
    arguments: dict[str, Any]


class ToolRuntime:
    def __init__(self) -> None:
        register_builtin_tools()

    def available_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        for tool_name in tool_registry.all_names():
            tool = tool_registry.get(tool_name)
            if tool is not None:
                tools.append(tool)
        return tools

    def render_tool_catalog(self) -> str:
        lines = ["Available tools:"]
        for tool in self.available_tools():
            lines.append(f"- {tool.name}: {tool.description}")
        return "\n".join(lines)

    async def execute(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        tool = tool_registry.get(name)
        if tool is None:
            raise ToolNotFoundError(f"tool not found: {name}")
        return await tool.run(arguments or {})

    @staticmethod
    def format_result(name: str, result: dict[str, Any]) -> str:
        if name == "terminal":
            stdout = str(result.get("stdout", "")).rstrip()
            stderr = str(result.get("stderr", "")).rstrip()
            exit_code = result.get("exit_code")
            timed_out = result.get("timed_out")

            lines = [f"exit_code: {exit_code}", f"timed_out: {timed_out}"]
            lines.append("stdout:")
            lines.append(stdout or "<empty>")
            lines.append("stderr:")
            lines.append(stderr or "<empty>")
            return "\n".join(lines)

        return json.dumps(result, ensure_ascii=False, indent=2)
