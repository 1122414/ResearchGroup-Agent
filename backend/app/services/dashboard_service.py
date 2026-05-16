from __future__ import annotations

from ..storage.repositories import (
    ApprovalRequestRepository,
    EvidenceRepository,
    ExperimentPlanRepository,
    RecoveryActionRepository,
    RunRepository,
    TaskRepository,
)
from .task_graph_service import task_graph_service


class DashboardService:
    def overview(self, run_id: str | None = None) -> dict:
        run = RunRepository.get_by_id(run_id) if run_id else next(iter(RunRepository.get_all()), None)
        if not run:
            return {
                "run": None,
                "critical_path": [],
                "blocked_tasks": [],
                "pending_approvals": [],
                "failed_or_retried": [],
                "evidence_coverage": 0,
                "experiment_completion": 0,
            }
        tasks = TaskRepository.get_all(run_id=run["id"])
        graph = task_graph_service.get_graph(run["id"])
        evidence = EvidenceRepository.get_by_run(run["id"])
        experiments = ExperimentPlanRepository.get_all(run_id=run["id"])
        experiment_completed = [item for item in experiments if item["status"] == "completed"]
        research_tasks = [task for task in tasks if task.get("task_type") != "report_writing"]
        evidence_task_ids = {item["task_id"] for item in evidence["sources"] if item.get("task_id")}
        return {
            "run": run,
            "critical_path": [task for task in tasks if task.get("is_critical_path")],
            "blocked_tasks": [task for task in tasks if task.get("status") == "blocked"],
            "pending_approvals": ApprovalRequestRepository.get_by_run(run["id"], status="pending"),
            "failed_or_retried": RecoveryActionRepository.get_by_run(run["id"]),
            "evidence_coverage": round(len(evidence_task_ids) / max(len(research_tasks), 1), 4),
            "experiment_completion": round(len(experiment_completed) / max(len(experiments), 1), 4) if experiments else 0,
            "graph": graph,
        }


dashboard_service = DashboardService()
