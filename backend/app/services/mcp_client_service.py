from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager

from ..core.config import settings
from ..core.logger import logger


class MCPClientService:
    """Thin adapter over the MCP Python SDK.

    Design goals:
    - Zero behavior change when disabled. ``MCP_ENABLED=false`` (default) or a
      missing/empty registry means every call degrades gracefully: capability
      listings are empty and ``call_tool`` raises a clear, catchable error.
    - Double gating. The master switch ``settings.mcp_enabled`` plus each
      server's own ``enabled`` flag in the registry file must both be true.
    - No connections on import or on health checks. Connections are opened
      lazily, per call, only for explicitly enabled servers.
    """

    def __init__(self) -> None:
        self._registry_cache: dict | None = None

    # ---------- registry ----------

    def _load_registry(self) -> list[dict]:
        if self._registry_cache is not None:
            return self._registry_cache
        path = settings.mcp_servers_path
        servers: list[dict] = []
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                servers = data.get("servers", []) if isinstance(data, dict) else []
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("[MCP] failed to read registry %s | error=%s", path, exc)
        else:
            logger.info("[MCP] registry not found at %s; no servers configured", path)
        self._registry_cache = servers
        return servers

    def reload(self) -> None:
        self._registry_cache = None

    def _mcp_available(self) -> bool:
        try:
            import mcp  # noqa: F401
        except ImportError:
            return False
        return True

    def enabled(self) -> bool:
        return bool(settings.mcp_enabled) and self._mcp_available()

    def list_servers(self) -> list[dict]:
        """Registry view (no connections). Safe for health endpoints."""
        servers = []
        for item in self._load_registry():
            servers.append(
                {
                    "name": item.get("name"),
                    "tier": item.get("tier"),
                    "transport": item.get("transport", "stdio"),
                    "enabled": bool(item.get("enabled")) and self.enabled(),
                    "description": item.get("description", ""),
                }
            )
        return servers

    def summary(self) -> dict:
        """Sync, connection-free summary for provider audit / health probe."""
        servers = self.list_servers()
        return {
            "enabled": self.enabled(),
            "mcp_installed": self._mcp_available(),
            "configured_servers": [s["name"] for s in servers],
            "enabled_servers": [s["name"] for s in servers if s["enabled"]],
            "servers": servers,
            "tools_probe": "on-demand",
        }

    def _resolve_enabled_server(self, name: str) -> dict:
        if not self.enabled():
            raise RuntimeError("MCP is disabled (set MCP_ENABLED=true and install the mcp package)")
        for item in self._load_registry():
            if item.get("name") == name:
                if not item.get("enabled"):
                    raise RuntimeError(f"MCP server '{name}' is disabled in the registry")
                return item
        raise RuntimeError(f"MCP server '{name}' is not configured")

    # ---------- connections ----------

    @asynccontextmanager
    async def _session(self, server: dict):
        from mcp import ClientSession

        transport = (server.get("transport") or "stdio").lower()
        if transport == "stdio":
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            env = os.environ.copy()
            env.update({str(k): str(v) for k, v in (server.get("env") or {}).items()})
            params = StdioServerParameters(
                command=server["command"],
                args=server.get("args", []),
                env=env,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
        elif transport in {"http", "streamable_http", "streamable-http"}:
            from mcp.client.streamable_http import streamablehttp_client

            url = server.get("url")
            if not url:
                raise RuntimeError(f"MCP server '{server.get('name')}' uses http transport but has no url")
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
        else:
            raise RuntimeError(f"Unsupported MCP transport: {transport}")

    # ---------- tool surface ----------

    async def list_tools(self, server_name: str) -> list[dict]:
        server = self._resolve_enabled_server(server_name)
        timeout = settings.mcp_call_timeout_seconds

        async def _run() -> list[dict]:
            async with self._session(server) as session:
                result = await session.list_tools()
                return [
                    {
                        "server": server_name,
                        "name": tool.name,
                        "description": tool.description or "",
                        "input_schema": getattr(tool, "inputSchema", None),
                    }
                    for tool in result.tools
                ]

        return await asyncio.wait_for(_run(), timeout=timeout)

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict | None = None) -> dict:
        server = self._resolve_enabled_server(server_name)
        timeout = settings.mcp_call_timeout_seconds

        async def _run() -> dict:
            async with self._session(server) as session:
                result = await session.call_tool(tool_name, arguments or {})
                return self._normalize_result(server_name, tool_name, result)

        return await asyncio.wait_for(_run(), timeout=timeout)

    @staticmethod
    def _normalize_result(server_name: str, tool_name: str, result) -> dict:
        text_parts: list[str] = []
        for block in getattr(result, "content", []) or []:
            text = getattr(block, "text", None)
            if text is not None:
                text_parts.append(text)
        return {
            "server": server_name,
            "tool": tool_name,
            "is_error": bool(getattr(result, "isError", False)),
            "text": "\n".join(text_parts),
            "structured": getattr(result, "structuredContent", None),
        }


mcp_client_service = MCPClientService()
