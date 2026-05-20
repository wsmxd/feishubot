from __future__ import annotations

import asyncio
import logging

from feishubot.ai.mcp.bridge import McpToolBridge
from feishubot.ai.mcp.client import MCPClient, get_mcp_client
from feishubot.ai.tools.registry import tool_registry

logger = logging.getLogger(__name__)


async def init_mcp_tools() -> MCPClient:
    client = get_mcp_client()
    await client.connect()

    if not client.connected:
        logger.info("MCP client not connected, no MCP tools to register")
        return client

    mcp_tools = client.list_tools()

    for tool_info in mcp_tools:
        tool_name = tool_info["name"]
        description = tool_info["description"]

        if tool_registry.get(tool_name) is not None:
            logger.warning(f"Tool '{tool_name}' already registered, skipping MCP registration")
            continue

        bridge = McpToolBridge(
            mcp_tool_name=tool_name,
            description=description,
            client=client,
        )
        tool_registry.register(tool_name, bridge)
        logger.info(f"Registered MCP tool: {tool_name}")

    return client


def init_mcp_tools_sync() -> MCPClient:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(init_mcp_tools(), loop)
        return future.result(timeout=30)

    return asyncio.run(init_mcp_tools())


__all__ = [
    "MCPClient",
    "McpToolBridge",
    "get_mcp_client",
    "init_mcp_tools",
    "init_mcp_tools_sync",
]
