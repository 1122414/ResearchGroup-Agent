"""
预留接口：ExternalMemory
预留长期记忆和知识库功能。
未来可接入向量数据库（如 Chroma、Pinecone）实现跨运行的知识积累。
MVP 阶段仅保留空实现，不做向量数据库。
"""

from typing import Optional


class ExternalMemory:
    def save_summary(self, agent_id: str, content: str):
        pass

    def retrieve(self, agent_id: str, query: str) -> list[str]:
        return []

    def get_context(self, agent_id: str) -> Optional[dict]:
        return None


external_memory = ExternalMemory()
