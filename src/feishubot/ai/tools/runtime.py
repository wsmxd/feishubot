from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml

from feishubot.ai.core.errors import ToolNotFoundError
from feishubot.ai.tools.base import Tool
from feishubot.ai.tools.builtins import register_builtin_tools
from feishubot.ai.tools.registry import tool_registry
from feishubot.config import settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ToolInvocation:
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ToolRoutingConfig:
    timeout_seconds: float | None = None


class ToolRuntime:
    def __init__(self, config_path: str | None = None) -> None:
        register_builtin_tools()
        self._enabled_tools: set[str] | None = None
        self._routing: dict[str, ToolRoutingConfig] = {}

        resolved_config_path = config_path or settings.ai_tools_config_path
        if resolved_config_path:
            self._load_config(Path(resolved_config_path).expanduser().resolve())

    def _load_config(self, config_path: Path) -> None:
        if not config_path.exists():
            raise ValueError(f"tool config file not found: {config_path}")

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if raw is None:
            return
        if not isinstance(raw, dict):
            raise ValueError("tool config must be a YAML object")

        enabled_tools = raw.get("enabled_tools")
        if enabled_tools is not None:
            if not isinstance(enabled_tools, list) or not all(
                isinstance(item, str) for item in enabled_tools
            ):
                raise ValueError("enabled_tools must be a list of strings")
            self._enabled_tools = {name.strip() for name in enabled_tools if name.strip()}

        routing = raw.get("routing")
        if routing is not None:
            if not isinstance(routing, dict):
                raise ValueError("routing must be an object")
            parsed_routing: dict[str, ToolRoutingConfig] = {}
            for tool_name, tool_routing in routing.items():
                if not isinstance(tool_name, str):
                    raise ValueError("routing keys must be tool names")
                if not isinstance(tool_routing, dict):
                    raise ValueError(f"routing for '{tool_name}' must be an object")

                timeout_seconds: float | None = None
                if "timeout_seconds" in tool_routing:
                    timeout_raw = tool_routing.get("timeout_seconds")
                    try:
                        timeout_seconds = float(timeout_raw)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            f"routing timeout_seconds for '{tool_name}' must be numeric"
                        ) from exc
                parsed_routing[tool_name.strip()] = ToolRoutingConfig(
                    timeout_seconds=timeout_seconds
                )

            self._routing = parsed_routing

    def _is_tool_enabled(self, name: str) -> bool:
        if self._enabled_tools is None:
            return True
        return name in self._enabled_tools

    def available_tools(self) -> list[Tool]:
        tools: list[Tool] = []
        for tool_name in tool_registry.all_names():
            if not self._is_tool_enabled(tool_name):
                continue
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
        if not self._is_tool_enabled(name):
            raise ToolNotFoundError(f"tool not enabled: {name}")

        tool = tool_registry.get(name)
        if tool is None:
            raise ToolNotFoundError(f"tool not found: {name}")

        effective_arguments = dict(arguments or {})
        tool_routing = self._routing.get(name)
        if tool_routing is not None and tool_routing.timeout_seconds is not None:
            effective_arguments.setdefault("timeout_seconds", tool_routing.timeout_seconds)

        validated_arguments = tool.validate_arguments(effective_arguments)
        start = perf_counter()
        try:
            result = await tool.run(validated_arguments)
        except Exception:
            elapsed_ms = int((perf_counter() - start) * 1000)
            logger.exception("tool execution failed: name=%s duration_ms=%s", name, elapsed_ms)
            raise

        elapsed_ms = int((perf_counter() - start) * 1000)
        logger.info("tool execution succeeded: name=%s duration_ms=%s", name, elapsed_ms)
        return result

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
