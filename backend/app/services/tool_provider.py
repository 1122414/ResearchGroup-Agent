from __future__ import annotations


class ToolProvider:
    def run(self, tool_name: str, input: dict) -> dict:
        raise NotImplementedError(f"工具 {tool_name} 尚未接入")

    def list_available(self) -> list[str]:
        return []

    def capabilities(self) -> list[dict]:
        return [
            {"name": "paper_search", "enabled": False},
            {"name": "web_search", "enabled": False},
            {"name": "github_search", "enabled": False},
            {"name": "code_runner", "enabled": False},
            {"name": "file_reader", "enabled": False},
            {"name": "chart_generator", "enabled": False},
            {"name": "zotero_connector", "enabled": False},
            {"name": "overleaf_connector", "enabled": False},
        ]


tool_provider = ToolProvider()
