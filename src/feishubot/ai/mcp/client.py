from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import ClientSessionGroup, StdioServerParameters
from mcp.client.session_group import SseServerParameters, StreamableHttpParameters

from feishubot.config import settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class McpServerConfig:
    name: str
    transport: str
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] | None = None


def _load_server_configs(config_path: Path) -> dict[str, McpServerConfig]:
    if not config_path.exists():
        raise ValueError(f"MCP servers config not found: {config_path}")

    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("MCP servers config must be a TOML table")

    servers_raw = raw.get("mcp_servers")
    if not isinstance(servers_raw, dict) or not servers_raw:
        return {}

    configs: dict[str, McpServerConfig] = {}
    for server_name, server_config in servers_raw.items():
        if not isinstance(server_name, str) or not server_name.strip():
            continue
        if not isinstance(server_config, dict):
            raise ValueError(f"mcp server '{server_name}' must be a TOML table")

        transport = str(server_config.get("transport", "stdio")).strip().lower()
        name = server_name.strip()

        if transport == "stdio":
            command = str(server_config.get("command", "")).strip()
            if not command:
                raise ValueError(f"mcp server '{name}' with stdio transport requires 'command'")
            args_raw = server_config.get("args")
            args = [str(a) for a in args_raw] if isinstance(args_raw, list) else None
            env_raw = server_config.get("env")
            env = dict(env_raw) if isinstance(env_raw, dict) else None
            cwd = str(server_config.get("cwd", "")).strip() or None

            configs[name] = McpServerConfig(
                name=name,
                transport=transport,
                command=command,
                args=args,
                env=env,
                cwd=cwd,
            )
        elif transport in {"streamable_http", "sse", "http"}:
            url = str(server_config.get("url", "")).strip()
            if not url:
                raise ValueError(f"mcp server '{name}' with {transport} transport requires 'url'")
            headers_raw = server_config.get("headers")
            headers = dict(headers_raw) if isinstance(headers_raw, dict) else None
            configs[name] = McpServerConfig(
                name=name, transport=transport, url=url, headers=headers
            )
        else:
            raise ValueError(f"unsupported transport '{transport}' for mcp server '{name}'")

    return configs


def _resolve_config_path() -> Path | None:
    configured = settings.mcp_servers_config_path.strip()
    if configured:
        return Path(configured).expanduser().resolve()

    default_path = Path(__file__).resolve().parents[4] / "mcp_servers.default.toml"
    if default_path.exists():
        raw = tomllib.loads(default_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("mcp_servers"):
            return default_path

    user_path = Path.cwd() / "mcp_servers.toml"
    if user_path.exists():
        return user_path

    return None


class MCPClient:
    def __init__(self) -> None:
        self._group: ClientSessionGroup | None = None
        self._server_configs: dict[str, McpServerConfig] = {}
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected and self._group is not None

    async def connect(self) -> None:
        if self._connected:
            logger.debug("MCP client already connected")
            return

        config_path = _resolve_config_path()
        if config_path is None:
            logger.info("No MCP servers config found, skipping MCP client initialization")
            return

        self._server_configs = _load_server_configs(config_path)
        if not self._server_configs:
            logger.info("No MCP servers configured, skipping MCP client initialization")
            return

        self._group = ClientSessionGroup()
        for server_name, server_config in self._server_configs.items():
            try:
                if server_config.transport == "stdio":
                    await self._connect_stdio(server_config)
                elif server_config.transport == "streamable_http":
                    await self._connect_streamable_http(server_config)
                elif server_config.transport in {"sse", "http"}:
                    await self._connect_sse(server_config)
            except Exception:  # noqa: BLE001
                logger.exception(
                    f"Failed to connect to MCP server '{server_name}' "
                    f"(transport={server_config.transport}, "
                    f"url={server_config.url or server_config.command})"
                )

        connected_count = len(self._group.tools) if self._group else 0
        if connected_count > 0:
            self._connected = True
            logger.info(
                f"MCP client connected, {connected_count} tool(s) available "
                f"from {len(self._server_configs)} server(s)"
            )
        else:
            logger.warning("MCP client initialized but no tools discovered from any server")

    async def _connect_stdio(self, config: McpServerConfig) -> None:
        merged_env: dict[str, str] | None = None
        if config.env:
            merged_env = dict(os.environ)
            merged_env.update(config.env)

        server_params = StdioServerParameters(
            command=config.command or "",
            args=config.args or [],
            env=merged_env,
            cwd=config.cwd,
        )
        await self._group.connect_to_server(server_params)
        logger.info(f"Connected to MCP server '{config.name}' via stdio")

    async def _connect_streamable_http(self, config: McpServerConfig) -> None:
        server_params = StreamableHttpParameters(
            url=config.url or "",
            headers=config.headers,
        )
        await self._group.connect_to_server(server_params)
        logger.info(f"Connected to MCP server '{config.name}' via streamable_http")

    async def _connect_sse(self, config: McpServerConfig) -> None:
        server_params = SseServerParameters(
            url=config.url or "",
            headers=config.headers,
        )
        await self._group.connect_to_server(server_params)
        logger.info(f"Connected to MCP server '{config.name}' via sse")

    async def disconnect(self) -> None:
        if self._group is not None:
            try:
                await self._group.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                logger.exception("Error during MCP client disconnect")
            self._group = None
        self._connected = False
        logger.info("MCP client disconnected")

    def list_tools(self) -> list[dict[str, Any]]:
        if not self.connected or self._group is None:
            return []
        tool_list = []
        for tool_name, tool in self._group.tools.items():
            tool_list.append(
                {
                    "name": tool_name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema or {},
                }
            )
        return tool_list

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self.connected or self._group is None:
            raise RuntimeError("MCP client not connected")

        result = await self._group.call_tool(name, arguments)

        content_parts: list[str] = []
        structured_data: Any = None
        for item in result.content:
            if hasattr(item, "text"):
                content_parts.append(item.text)
            elif hasattr(item, "data"):
                structured_data = item.data

        if result.isError:
            error_text = "\n".join(content_parts) or "unknown MCP tool error"
            raise RuntimeError(f"MCP tool '{name}' error: {error_text}")

        if structured_data is not None:
            return {"content": structured_data, "text": "\n".join(content_parts)}

        return {"content": "\n".join(content_parts)}


_mcp_client: MCPClient | None = None


def get_mcp_client() -> MCPClient:
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client
