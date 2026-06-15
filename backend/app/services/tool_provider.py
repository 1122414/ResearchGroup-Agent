from __future__ import annotations

from .mcp_client_service import mcp_client_service


class ToolProvider:
    """Unified tool entry point, now backed by the MCP adapter layer.

    When MCP is disabled (the default) this behaves like the previous stub:
    no tools are advertised and ``run``/``arun`` raise a clear error. Enabling
    MCP and a server in the registry makes that server's tools callable here.
    """

    async def arun(self, server_name: str, tool_name: str, input: dict | None = None) -> dict:
        return await mcp_client_service.call_tool(server_name, tool_name, input or {})

    async def run(self, server_name: str, tool_name: str, input: dict | None = None) -> dict:
        return await self.arun(server_name, tool_name, input)

    async def list_tools(self, server_name: str) -> list[dict]:
        return await mcp_client_service.list_tools(server_name)

    def list_available(self) -> list[str]:
        return [server["name"] for server in mcp_client_service.list_servers() if server["enabled"]]

    def capabilities(self) -> list[dict]:
        return [
            {
                "name": server["name"],
                "tier": server.get("tier"),
                "transport": server.get("transport"),
                "enabled": server["enabled"],
                "description": server.get("description", ""),
            }
            for server in mcp_client_service.list_servers()
        ]


tool_provider = ToolProvider()
