from __future__ import annotations

import uuid
from datetime import datetime

from ..core.config import settings
from ..storage.repositories import RecoveryActionRepository, TaskAttemptRepository, TaskDependencyRepository, TaskRepository
from .task_graph_service import task_graph_service


class TaskRecoveryService:
    def start_attempt(self, task: dict) -> dict:
        attempt_number = int(task.get("attempt_count", 0)) + 1
        attempt = {
            "id": f"attempt_{uuid.uuid4().hex[:10]}",
            "run_id": task["run_id"],
            "task_id": task["id"],
            "attempt_number": attempt_number,
            "status": "running",
            "started_at": datetime.now().isoformat(),
        }
        TaskAttemptRepository.insert(attempt)
        TaskRepository.update_status(task["id"], "running", attempt_count=attempt_number)
        return attempt

    def complete_attempt(self, task_id: str, attempt_id: str, checkpoint: str | None = None):
        TaskAttemptRepository.update(
            attempt_id,
            status="completed",
            checkpoint=checkpoint,
            completed_at=datetime.now().isoformat(),
        )
        if checkpoint:
            task = TaskRepository.get_by_id(task_id)
            if task:
                TaskRepository.update_status(task_id, task.get("status", "running"), last_checkpoint=checkpoint)

    def fail_attempt(self, attempt_id: str, failure_type: str, failure_message: str):
        TaskAttemptRepository.update(
            attempt_id,
            status="failed",
            failure_type=failure_type,
            failure_message=failure_message,
            completed_at=datetime.now().isoformat(),
        )

    def retry(self, task: dict, reason: str = "manual_retry") -> dict:
        return self._reset_with_action(task, "retry", reason, {"from_status": task.get("status")})

    def resume_from_checkpoint(self, task: dict, reason: str = "manual_resume") -> dict:
        return self._reset_with_action(
            task,
            "resume_checkpoint",
            reason,
            {"from_status": task.get("status"), "checkpoint": task.get("last_checkpoint")},
        )

    def rerun_branch(self, task: dict, reason: str = "manual_rerun_branch") -> dict:
        affected = [task["id"], *task_graph_service.descendants(task["run_id"], task["id"])]
        action = {
            "id": f"recovery_{uuid.uuid4().hex[:10]}",
            "run_id": task["run_id"],
            "task_id": task["id"],
            "action_type": "rerun_branch",
            "status": "completed",
            "reason": reason,
            "payload": {"affected_task_ids": affected},
            "created_at": datetime.now().isoformat(),
        }
        RecoveryActionRepository.insert(action)
        for task_id in affected:
            current = TaskRepository.get_by_id(task_id)
            if not current:
                continue
            TaskRepository.update_status(
                task_id,
                "pending",
                blocked_reason=None,
                review_result=None,
                review_feedback=None,
            )
        return action

    def create_revision_task(self, task: dict, feedback: str) -> dict | None:
        root_task = self._root_task(task)
        root_task_id = root_task["id"]
        existing_revisions = [
            item
            for item in TaskRepository.get_all(run_id=task["run_id"])
            if item.get("revision_of_task_id") == root_task_id
        ]
        existing = next(
            (
                item
                for item in TaskRepository.get_all(run_id=task["run_id"])
                if item.get("revision_of_task_id") == root_task_id
                and item.get("id") != task.get("id")
                and item.get("status") not in {"completed", "failed", "archived"}
            ),
            None,
        )
        if existing:
            return existing
        if len(existing_revisions) >= settings.task_max_revision_rounds:
            return None

        now = datetime.now().isoformat()
        revision_task = {
            "id": f"task_revision_{uuid.uuid4().hex[:8]}",
            "title": f"返工：{root_task['title']}",
            "description": self._revision_description(root_task, feedback or task.get("review_feedback")),
            "task_type": root_task["task_type"],
            "required_skills": root_task.get("required_skills", {}),
            "priority": min(int(root_task.get("priority", 5)) + 1, 10),
            "complexity": max(int(root_task.get("complexity", 5)) - 1, 1),
            "decomposability": root_task.get("decomposability", 5),
            "status": "pending",
            "owner_agent": root_task.get("owner_agent"),
            "collaborator_agents": root_task.get("collaborator_agents", []),
            "subtasks": [],
            "outputs": [],
            "review_result": None,
            "review_feedback": None,
            "run_id": task["run_id"],
            "assignment_info": root_task.get("assignment_info", {}),
            "subagent_triggered": False,
            "blocked_reason": None,
            "parallelizable": root_task.get("parallelizable", True),
            "is_critical_path": root_task.get("is_critical_path", False),
            "attempt_count": 0,
            "last_checkpoint": None,
            "revision_of_task_id": root_task_id,
            "created_at": now,
            "updated_at": now,
        }
        TaskRepository.insert(revision_task)
        TaskDependencyRepository.replace_for_task(revision_task["id"], TaskDependencyRepository.get_for_task(root_task_id))
        subtasks = list(dict.fromkeys([*(root_task.get("subtasks") or []), revision_task["id"]]))
        TaskRepository.update_status(
            root_task_id,
            "blocked",
            blocked_reason=f"等待返工任务完成: {revision_task['id']}",
            subtasks=subtasks,
        )
        task_graph_service.recompute_critical_path(task["run_id"])
        return revision_task

    @staticmethod
    def _revision_description(root_task: dict, feedback: str | None) -> str:
        original = str(root_task.get("description") or "").strip()
        feedback_text = str(feedback or "").strip()
        if not feedback_text:
            return original or "根据导师反馈完成返工。"
        if not original:
            return f"原始任务：{root_task.get('title', '')}\n返工要求：{feedback_text}"
        return f"原始任务：{original}\n返工要求：{feedback_text}"

    @staticmethod
    def _root_task(task: dict) -> dict:
        current = task
        visited: set[str] = set()
        while current.get("revision_of_task_id") and current["id"] not in visited:
            visited.add(current["id"])
            parent = TaskRepository.get_by_id(current["revision_of_task_id"])
            if not parent:
                break
            current = parent
        return current

    def _reset_with_action(self, task: dict, action_type: str, reason: str, payload: dict) -> dict:
        action = {
            "id": f"recovery_{uuid.uuid4().hex[:10]}",
            "run_id": task["run_id"],
            "task_id": task["id"],
            "action_type": action_type,
            "status": "completed",
            "reason": reason,
            "payload": payload,
            "created_at": datetime.now().isoformat(),
        }
        RecoveryActionRepository.insert(action)
        TaskRepository.update_status(
            task["id"],
            "pending",
            blocked_reason=None,
            review_result=None,
            review_feedback=None,
        )
        return action


task_recovery_service = TaskRecoveryService()
