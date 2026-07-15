from __future__ import annotations

import json
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

    def can_create_revision(self, task: dict) -> bool:
        """Whether another revision round can still be spawned for this task's root.

        Pure check (no side effects): mirrors the gating logic in
        create_revision_task so callers can detect a dead-end without mutating
        any state. Only a newer active sibling is reusable; an older rejected
        round never becomes executable again.
        """
        root_task = self._root_task(task)
        root_task_id = root_task["id"]
        run_tasks = TaskRepository.get_all(run_id=task["run_id"])
        existing_revisions = [
            item for item in run_tasks if item.get("revision_of_task_id") == root_task_id
        ]
        if self._newer_live_revision(task, existing_revisions):
            return True
        return len(existing_revisions) < settings.task_max_revision_rounds

    def create_revision_task(self, task: dict, feedback: str | dict) -> dict | None:
        root_task = self._root_task(task)
        root_task_id = root_task["id"]
        existing_revisions = [
            item
            for item in TaskRepository.get_all(run_id=task["run_id"])
            if item.get("revision_of_task_id") == root_task_id
        ]
        existing = self._newer_live_revision(task, existing_revisions)
        if existing:
            return existing
        if len(existing_revisions) >= settings.task_max_revision_rounds:
            return None

        now = datetime.now().isoformat()
        revision_task = {
            "id": f"task_revision_{uuid.uuid4().hex[:8]}",
            "title": f"返工：{root_task['title']}",
            "description": self._revision_description(
                root_task,
                task,
                feedback or task.get("review_result") or task.get("review_feedback"),
            ),
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
            "subquestion_id": root_task.get("subquestion_id"),
            "hypothesis_id": root_task.get("hypothesis_id"),
            "milestone_id": root_task.get("milestone_id"),
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

    def reopen_for_thesis_length(self, task: dict, adjustment: dict) -> dict:
        root = self._root_task(task)
        direction = adjustment["direction"]
        verb = "扩展" if direction == "expand" else "压缩"
        target = int(adjustment["target"])
        feedback = {
            "feedback": (
                f"整篇论文当前 {adjustment['total']} 词，院校范围为 "
                f"{adjustment['minimum']}–{adjustment['maximum'] or '不限上限'} 词。"
                f"仅对本章做有界{verb}，将正文控制在 {max(target - 30, 1)}–{target + 30} 词。"
                "保留事实、数值、段落 ID、support_ids 与限定边界；不得新增来源或重复凑字。"
            ),
            "revision_plan": [{
                "layer": "institutional_total_length",
                "issue": "整篇论文总字数超出冻结院校范围",
                "required_change": f"本章有界{verb}到目标区间，不改变研究结论",
            }],
        }
        description = self._revision_description(root, task, feedback)
        TaskRepository.update_status(
            task["id"], "pending", description=description, outputs=[], attempt_count=0,
            blocked_reason=None, review_result=None, review_feedback=None,
        )
        if task.get("revision_of_task_id"):
            TaskRepository.update_status(
                root["id"], "blocked", blocked_reason=f"等待论文总字数拟合: {task['id']}",
                review_result=None, review_feedback=None,
            )
        return TaskRepository.get_by_id(task["id"]) or task

    def reopen_thesis_in_place(self, task: dict, feedback: str | dict) -> dict:
        root = self._root_task(task)
        description = self._revision_description(root, task, feedback)
        TaskRepository.update_status(
            task["id"], "pending", description=description, outputs=[],
            blocked_reason=None, review_result=None, review_feedback=None,
        )
        if task.get("revision_of_task_id"):
            TaskRepository.update_status(
                root["id"], "blocked", blocked_reason=f"等待末轮原地定点返工: {task['id']}",
                review_result=None, review_feedback=None,
            )
        return TaskRepository.get_by_id(task["id"]) or task

    @staticmethod
    def _newer_live_revision(task: dict, revisions: list[dict]) -> dict | None:
        """Return only a genuinely newer active revision for idempotent reuse."""
        current_created = str(task.get("created_at") or "")
        is_root = not task.get("revision_of_task_id")
        live_statuses = {"pending", "assigned", "blocked", "running", "waiting_subagent", "waiting_review"}
        candidates = [
            item for item in revisions
            if item.get("id") != task.get("id")
            and item.get("status") in live_statuses
            and (is_root or str(item.get("created_at") or "") > current_created)
        ]
        return max(candidates, key=lambda item: str(item.get("created_at") or ""), default=None)

    @staticmethod
    def _revision_description(root_task: dict, latest_task: dict, feedback: str | dict | None) -> str:
        original = str(root_task.get("description") or "").strip()
        if isinstance(feedback, dict):
            revision_plan = feedback.get("revision_plan") or []
            feedback_text = str(feedback.get("feedback") or "").strip()
            if revision_plan:
                feedback_text += "\n逐项修改清单：\n" + json.dumps(
                    revision_plan, ensure_ascii=False, indent=2
                )
        else:
            feedback_text = str(feedback or "").strip()
        outputs = latest_task.get("outputs") or []
        previous = outputs[-1] if outputs else None
        is_thesis_chapter = root_task.get("task_type") == "thesis_chapter"
        compact_previous = TaskRecoveryService._compact_previous(
            previous, include_chapter=is_thesis_chapter,
        )
        serialized_previous = json.dumps(compact_previous, ensure_ascii=False, indent=2)
        previous_text = (
            "\n上一版交付物（必须在此基础上修改，不得只复述缺口）：\n"
            + (serialized_previous if is_thesis_chapter else serialized_previous[:6000])
            if compact_previous
            else ""
        )
        instruction = (
            "\n返工交付规则：逐项落实修改清单并提交可直接审核的完整最终交付物；"
            "协作者意见仅用于检查风险，不能替代父任务交付物。"
        )
        if not feedback_text:
            return original or "根据导师反馈完成返工。"
        if not original:
            return f"原始任务：{root_task.get('title', '')}\n返工要求：{feedback_text}{previous_text}{instruction}"
        return f"原始任务：{original}\n返工要求：{feedback_text}{previous_text}{instruction}"

    @staticmethod
    def _compact_previous(previous, include_chapter: bool = False) -> dict | list | None:
        if isinstance(previous, list):
            return previous[:10]
        if not isinstance(previous, dict):
            return None
        compact = {
            key: previous.get(key)
            for key in (
                "summary", "findings", "deliverables", "risks", "next_steps", "claims",
                "hypotheses", "uncertainties", "references_used", "academic_integrity",
                "insufficient_evidence", "integrity_blocked",
            )
            if previous.get(key) is not None
        }
        if include_chapter and isinstance(previous.get("chapter"), dict):
            compact["chapter"] = previous["chapter"]
        experiment = previous.get("reproducible_experiment")
        if isinstance(experiment, dict):
            metrics = experiment.get("metrics") or {}
            compact["reproducible_experiment"] = {
                "summary": experiment.get("summary"),
                "experiment_ran": experiment.get("experiment_ran"),
                "publishable": experiment.get("publishable"),
                "artifact_class": experiment.get("artifact_class"),
                "metrics": {
                    key: metrics.get(key)
                    for key in (
                        "rows", "best_strategy", "statistical_analysis", "randomness_audit",
                        "artifact_hashes", "preregistration_trace",
                    )
                },
                "reproduction": experiment.get("reproduction"),
                "artifacts": experiment.get("artifacts"),
                "preregistration_trace": experiment.get("preregistration_trace"),
            }
        return compact

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
