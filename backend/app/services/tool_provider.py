"""
预留接口：ToolProvider
未来工具接入统一入口，MVP 阶段仅保留空实现。

未来工具：
- paper_search: 文献检索
- web_search: 网络搜索
- github_search: GitHub 项目搜索
- code_runner: 代码执行沙箱
- file_reader: 文件读取
- chart_generator: 图表生成
- zotero_connector: Zotero 连接器
- overleaf_connector: Overleaf 连接器
"""

from typing import Optional


class ToolProvider:
    def run(self, tool_name: str, input: dict) -> dict:
        raise NotImplementedError("ToolProvider 尚未实现，MVP 阶段仅保留接口。")

    def list_available(self) -> list[str]:
        return []


tool_provider = ToolProvider()
