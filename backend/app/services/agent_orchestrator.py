"""
预留接口：AgentOrchestrator
预留替换为 LangGraph / AutoGen / CrewAI 等框架的接入接口。
MVP 阶段仅保留空实现，当前使用自研轻量调度器。
"""

from typing import Optional


class AgentOrchestrator:
    def run_task(self, task_id: str) -> dict:
        raise NotImplementedError("AgentOrchestrator 尚未实现，MVP 阶段仅保留接口。")

    def run_step(self, run_id: str) -> dict:
        raise NotImplementedError("AgentOrchestrator 尚未实现，MVP 阶段仅保留接口。")

    def get_status(self, run_id: str) -> dict:
        return {"status": "not_implemented", "message": "当前使用自研调度器"}


agent_orchestrator = AgentOrchestrator()
