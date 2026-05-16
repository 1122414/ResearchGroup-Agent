from __future__ import annotations

from .task_graph_service import task_graph_service


class AgentOrchestrator:
    def plan_run(self, run_id: str) -> dict:
        return task_graph_service.get_graph(run_id)

    def advance(self, run_id: str) -> dict:
        return {"run_id": run_id, "status": "delegated_to_run_execution_service"}

    def resume_from_checkpoint(self, run_id: str, checkpoint: str | None = None) -> dict:
        return {"run_id": run_id, "checkpoint": checkpoint, "status": "delegated_to_run_execution_service"}

    def get_graph(self, run_id: str) -> dict:
        return task_graph_service.get_graph(run_id)

    def run_task(self, task_id: str) -> dict:
        raise NotImplementedError("任务执行仍由现有 RunExecutionService 承担")

    def run_step(self, run_id: str) -> dict:
        return self.advance(run_id)

    def get_status(self, run_id: str) -> dict:
        return {"run_id": run_id, "status": "adapter_ready"}


agent_orchestrator = AgentOrchestrator()
