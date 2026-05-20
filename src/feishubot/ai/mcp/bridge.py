from __future__ import annotations

import logging
from typing import Any

from feishubot.ai.mcp.client import MCPClient, get_mcp_client
from feishubot.ai.tools.base import Tool

logger = logging.getLogger(__name__)


class McpToolBridge(Tool):
    name: str
    description: str
    args_model = None

    def __init__(
        self, *, mcp_tool_name: str, description: str, client: MCPClient | None = None
    ) -> None:
        self.name = mcp_tool_name
        self.description = description
        self._client = client or get_mcp_client()

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self._client.call_tool(self.name, arguments)
            if isinstance(result.get("content"), str):
                return {"result": result["content"]}
            return result
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"MCP tool '{self.name}' execution failed")
            return {"error": str(exc)}
