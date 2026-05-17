import asyncio
from datetime import datetime

from fastapi import HTTPException

from ..core.config import settings
from ..core.logger import logger
from ..models.run import RunStatus
from ..storage.repositories import (
    AgentRepository,
    ApprovalRequestRepository,
    LLMUsageRepository,
    RunEventRepository,
    RunRepository,
    SubAgentRepository,
    TaskRepository,
)
from .approval_service import approval_service
from .report_service import report_service
from .research_loop_service import research_loop_service
from .review_service import review_service
from .run_event_service import run_event_service
from .skill_reflection_service import skill_reflection_service
from .subagent_service import subagent_service
from .task_decomposer import task_decomposer
from .task_executor import task_executor
from .task_graph_service import task_graph_service
from .task_recovery_service import task_recovery_service
from .task_scheduler import task_scheduler


class RunCancelled(Exception):
    pass


class RunExecutionService:
    def __init__(self) -> None:
        self._active_tasks: dict[str, asyncio.Task] = {}

    async def execute(self, run_id: str) -> dict:
        self._register_active_task(run_id)
        logger.info("[RunExecution] execute started | run_id=%s", run_id)
        run = RunRepository.get_by_id(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="运行不存在")
        if run.get("status") in (RunStatus.cancelling.value, RunStatus.cancelled.value):
            return self._cancel_now(run_id)

        try:
            tasks = TaskRepository.get_all(run_id=run_id)
            if not tasks:
                tasks = await self._initialize_run(run)
            else:
                self._ensure_scheduling(tasks, run_id)

            if self._has_pending_approval(run_id):
                return self._pause_for_confirmation(run_id)

            self._assert_not_cancelled(run_id)
            await self._execute_research_flow(run_id)
            if self._has_pending_approval(run_id):
                return self._pause_for_confirmation(run_id)

            tasks = TaskRepository.get_all(run_id=run_id)
            research_tasks = [task for task in tasks if task.get("task_type") != "report_writing"]
            if any(task.get("status") != "completed" for task in research_tasks):
                RunRepository.update_status(run_id, RunStatus.reviewing.value, current_step="等待研究任务完成或返工")
                return self.get_summary(run_id)

            while True:
                loop_tasks = research_loop_service.expand_once(run_id)
                if not loop_tasks:
                    break
                RunRepository.update_status(run_id, RunStatus.executing.value, current_step="根据研究缺口进入下一轮")
                run_event_service.emit(
                    run_id,
                    "research_loop.expanded",
                    "research_loop",
                    "已生成下一轮研究任务",
                    f"根据研究缺口新增 {len(loop_tasks)} 个任务",
                    payload={"task_ids": [item["id"] for item in loop_tasks]},
                )
                self._ensure_scheduling(TaskRepository.get_all(run_id=run_id), run_id)
                await self._execute_research_flow(run_id)
                if self._has_pending_approval(run_id):
                    return self._pause_for_confirmation(run_id)
                tasks = TaskRepository.get_all(run_id=run_id)
                research_tasks = [task for task in tasks if task.get("task_type") != "report_writing"]
                if any(task.get("status") != "completed" for task in research_tasks):
                    RunRepository.update_status(run_id, RunStatus.reviewing.value, current_step="等待下一轮研究任务完成")
                    return self.get_summary(run_id)

            await self._execute_writing_flow(run_id)
            if self._has_pending_approval(run_id):
                return self._pause_for_confirmation(run_id)

            tasks = TaskRepository.get_all(run_id=run_id)
            writing_tasks = [task for task in tasks if task.get("task_type") == "report_writing"]
            if writing_tasks and any(task.get("status") != "completed" for task in writing_tasks):
                RunRepository.update_status(run_id, RunStatus.reviewing.value, current_step="等待写作任务完成或返工")
                return self.get_summary(run_id)

            if not self._ensure_approval(
                run_id,
                "report_publish",
                None,
                "生成最终报告",
                "研究任务均已完成，请确认是否生成最终报告。",
            ):
                return self._pause_for_confirmation(run_id)

            self._assert_not_cancelled(run_id)
            RunRepository.update_status(run_id, RunStatus.reporting.value, current_step="生成最终研究报告")
            run_event_service.emit(run_id, "phase.started", "report", "生成最终研究报告", "写作研究生与导师开始整理最终报告")
            updated_run = RunRepository.get_by_id(run_id)
            await report_service.generate(updated_run)
            run_event_service.emit(run_id, "report.created", "report", "最终报告已生成", "最终 Markdown 报告已写入 artifacts")
            completed_at = datetime.now().isoformat()
            RunRepository.update_status(run_id, RunStatus.completed.value, current_step="完成", completed_at=completed_at)
            self._reset_agents(run_id)
            run_event_service.emit(run_id, "run.completed", "run", "运行完成", "全部任务已归档，Agent 已回到空闲状态")
            return self.get_summary(run_id)
        except (RunCancelled, asyncio.CancelledError):
            return self._cancel_now(run_id)
        except Exception as exc:
            RunRepository.update_status(run_id, RunStatus.failed.value, current_step=f"执行失败: {exc}", completed_at=datetime.now().isoformat())
            self._reset_agents(run_id, blocked=True)
            run_event_service.emit(run_id, "run.failed", "error", "运行失败", str(exc))
            logger.error("[RunExecution] execute failed | run_id=%s | error=%s", run_id, exc, exc_info=True)
            raise
        finally:
            self._unregister_active_task(run_id)

    async def _initialize_run(self, run: dict) -> list[dict]:
        run_id = run["id"]
        started_at = run.get("started_at") or datetime.now().isoformat()
        RunRepository.update_status(run_id, RunStatus.decomposing.value, current_step="导师拆解研究任务", started_at=started_at)
        run_event_service.emit(run_id, "phase.started", "decompose", "导师拆解研究任务", "导师 Agent 生成任务图")
        tasks = await task_decomposer.decompose(run["research_goal"], run_id)
        task_graph_service.build_default_graph(tasks)
        RunRepository.update_status(run_id, RunStatus.decomposing.value, task_ids=[task["id"] for task in tasks], current_step="任务拆解完成")
        for task in tasks:
            run_event_service.emit(
                run_id,
                "task.created",
                "decompose",
                "任务已创建",
                task["title"],
                task_id=task["id"],
                payload={"task_type": task.get("task_type"), "priority": task.get("priority")},
            )
        run_event_service.emit(run_id, "phase.completed", "decompose", "任务拆解完成", f"共生成 {len(tasks)} 个任务")
        self._ensure_scheduling(tasks, run_id)
        return TaskRepository.get_all(run_id=run_id)

    def _ensure_scheduling(self, tasks: list[dict], run_id: str) -> None:
        unscheduled = [task for task in tasks if not task.get("owner_agent")]
        if not unscheduled:
            return
        RunRepository.update_status(run_id, RunStatus.scheduling.value, current_step="调度研究生 Agent")
        assignments = task_scheduler.assign_all(unscheduled)
        current_assignments = (RunRepository.get_by_id(run_id) or {}).get("agent_assignments", {})
        RunRepository.update_status(run_id, RunStatus.scheduling.value, agent_assignments=assignments, current_step="任务调度完成")
        RunRepository.update_status(
            run_id,
            RunStatus.scheduling.value,
            agent_assignments={**current_assignments, **assignments},
            current_step="任务调度完成",
        )
        for task_id, assignment in assignments.items():
            run_event_service.emit(
                run_id,
                "task.assigned",
                "schedule",
                "任务已分配",
                f"负责人：{assignment.get('owner') or '未分配'}",
                task_id=task_id,
                agent_id=assignment.get("owner"),
                payload=assignment,
            )

    async def _execute_research_flow(self, run_id: str) -> None:
        while True:
            tasks = TaskRepository.get_all(run_id=run_id)
            research_tasks = [task for task in tasks if task.get("task_type") != "report_writing"]
            if not research_tasks:
                return
            before = [(task["id"], task.get("status")) for task in research_tasks]
            RunRepository.update_status(run_id, RunStatus.executing.value, current_step="研究任务执行中")
            await self._execute_ready_tasks(run_id, research_tasks)
            await self._review_task_batch(run_id, research_tasks)
            if self._has_pending_approval(run_id):
                return
            refreshed = TaskRepository.get_all(run_id=run_id)
            latest_research = [task for task in refreshed if task.get("task_type") != "report_writing"]
            if all(task.get("status") == "completed" for task in latest_research):
                return
            after = [(task["id"], task.get("status")) for task in latest_research]
            if after == before:
                return

    async def _execute_writing_flow(self, run_id: str) -> None:
        tasks = TaskRepository.get_all(run_id=run_id)
        writing_tasks = [task for task in tasks if task.get("task_type") == "report_writing"]
        if not writing_tasks:
            return
        RunRepository.update_status(run_id, RunStatus.executing.value, current_step="写作任务执行中")
        await self._execute_ready_tasks(run_id, writing_tasks)
        await self._review_task_batch(run_id, writing_tasks)

    async def _execute_ready_tasks(self, run_id: str, tasks: list[dict]) -> None:
        ordered = task_graph_service.topological_order(TaskRepository.get_all(run_id=run_id))
        task_ids = {task["id"] for task in tasks}
        for task in ordered:
            if task["id"] not in task_ids:
                continue
            latest = TaskRepository.get_by_id(task["id"]) or task
            ready_ids = {item["id"] for item in task_graph_service.ready_tasks(TaskRepository.get_all(run_id=run_id))}
            if latest.get("status") == "completed" or latest["id"] not in ready_ids:
                continue
            if latest.get("task_type") == "experiment_design" and not self._ensure_approval(
                run_id,
                "experiment_execute",
                latest["id"],
                "执行实验任务",
                f"将开始执行高风险实验任务：{latest.get('title', '')}",
            ):
                continue
            await self._execute_one_task(run_id, latest)

    async def _execute_one_task(self, run_id: str, task: dict) -> None:
        self._assert_not_cancelled(run_id)
        owner = task.get("owner_agent")
        if not owner:
            return
        TaskRepository.update_status(task["id"], "running", blocked_reason=None)
        run_event_service.emit(run_id, "task.started", "execute", "任务开始执行", task.get("title", ""), task_id=task["id"], agent_id=owner)
        attempt = task_recovery_service.start_attempt(task)
        try:
            agent = AgentRepository.get_by_id(owner)
            if agent and subagent_service.can_create_subagent(task, agent):
                TaskRepository.update_status(task["id"], "running", subagent_triggered=True)
                run_event_service.emit(run_id, "subagent.created", "subagent", "SubAgent 已创建", "任务复杂，研究生请求临时协作", task_id=task["id"], agent_id=owner)
                await subagent_service.create_and_execute(owner, task)
                self._assert_not_cancelled(run_id)
                run_event_service.emit(run_id, "subagent.completed", "subagent", "SubAgent 已完成", "结果已返回给研究生 Agent", task_id=task["id"], agent_id=owner)
            latest_task = TaskRepository.get_by_id(task["id"]) or task
            await task_executor.execute(latest_task)
            self._assert_not_cancelled(run_id)
            task_recovery_service.complete_attempt(task["id"], attempt["id"], checkpoint="task_output_created")
            run_event_service.emit(run_id, "task.output_created", "execute", "任务输出已生成", task.get("title", ""), task_id=task["id"], agent_id=owner)
        except Exception as exc:
            task_recovery_service.fail_attempt(attempt["id"], type(exc).__name__, str(exc))
            TaskRepository.update_status(task["id"], "failed", blocked_reason=str(exc))
            run_event_service.emit(run_id, "task.failed", "execute", "任务执行失败", str(exc), task_id=task["id"], agent_id=owner)

    async def _review_task_batch(self, run_id: str, tasks: list[dict]) -> None:
        for task in tasks:
            self._assert_not_cancelled(run_id)
            latest_task = TaskRepository.get_by_id(task["id"]) or task
            if latest_task.get("status") == "running" and latest_task.get("outputs"):
                TaskRepository.update_status(task["id"], "waiting_review")
                run_event_service.emit(run_id, "review.started", "review", "导师开始审核", latest_task.get("title", ""), task_id=task["id"], agent_id=latest_task.get("owner_agent"))
                review = await review_service.review(latest_task)
                run_event_service.emit(run_id, "review.completed", "review", "导师审核完成", review.get("feedback", ""), task_id=task["id"], agent_id=latest_task.get("owner_agent"), payload=review)
                latest_after_review = TaskRepository.get_by_id(task["id"]) or latest_task
                created_skills = skill_reflection_service.capture_after_review(latest_after_review, review)
                if created_skills:
                    run_event_service.emit(
                        run_id,
                        "skill.batch_created",
                        "skill",
                        "任务经验沉淀为 Skill",
                        f"共沉淀 {len(created_skills)} 条 skill 候选",
                        task_id=task["id"],
                        agent_id=latest_task.get("owner_agent"),
                        payload={"skill_ids": [skill["id"] for skill in created_skills]},
                    )
                if review.get("requires_revision"):
                    revision_task = task_recovery_service.create_revision_task(latest_after_review, review.get("feedback", ""))
                    request = approval_service.ensure_pending(
                        run_id,
                        "revision_required",
                        "导师要求返工",
                        review.get("feedback", "导师要求补充修改后重做"),
                        task_id=task["id"],
                        payload={"revision_task_id": revision_task["id"]},
                    )
                    if self._auto_mode_enabled():
                        approval_service.resolve(request["id"], True, resolved_by="system:auto")
                        TaskRepository.update_status(revision_task["id"], "pending", blocked_reason=None)

    def request_cancel(self, run_id: str, reason: str = "用户取消运行") -> dict:
        run = RunRepository.get_by_id(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="运行不存在")
        if run.get("status") in (RunStatus.completed.value, RunStatus.failed.value, RunStatus.cancelled.value):
            return run
        if run.get("status") in (RunStatus.created.value, RunStatus.queued.value):
            RunRepository.update_status(
                run_id,
                RunStatus.cancelled.value,
                current_step="运行已取消",
                cancel_requested_at=datetime.now().isoformat(),
                cancel_reason=reason,
                completed_at=datetime.now().isoformat(),
            )
            run_event_service.emit(run_id, "run.cancelled", "cancel", "运行已取消", reason)
            return RunRepository.get_by_id(run_id)
        RunRepository.update_status(
            run_id,
            RunStatus.cancelling.value,
            current_step="等待取消",
            cancel_requested_at=datetime.now().isoformat(),
            cancel_reason=reason,
        )
        run_event_service.emit(run_id, "run.cancel_requested", "cancel", "请求取消运行", reason)
        self._cancel_active_task(run_id)
        return self._cancel_now(run_id)["run"]

    def get_summary(self, run_id: str) -> dict:
        run = RunRepository.get_by_id(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="运行不存在")
        if run.get("status") == RunStatus.cancelling.value:
            return self._cancel_now(run_id)
        tasks = TaskRepository.get_all(run_id=run_id)
        agents = AgentRepository.get_all()
        subagents = SubAgentRepository.get_by_run(run_id)
        usage = LLMUsageRepository.get_summary(run_id)
        counts = {
            "tasks_total": len(tasks),
            "tasks_pending": len([task for task in tasks if task.get("status") == "pending"]),
            "tasks_running": len([task for task in tasks if task.get("status") == "running"]),
            "tasks_blocked": len([task for task in tasks if task.get("status") == "blocked"]),
            "tasks_completed": len([task for task in tasks if task.get("status") == "completed"]),
            "tasks_need_revision": len([task for task in tasks if task.get("status") == "need_revision"]),
            "tasks_failed": len([task for task in tasks if task.get("status") == "failed"]),
            "subagents_total": len(subagents),
            "pending_approvals": len(ApprovalRequestRepository.get_by_run(run_id, status="pending")),
        }
        return {
            "run": run,
            "counts": counts,
            "usage": usage,
            "latest_event": RunEventRepository.get_latest(run_id),
            "tasks": tasks,
            "agents": agents,
        }

    def _pause_for_confirmation(self, run_id: str) -> dict:
        RunRepository.update_status(run_id, RunStatus.waiting_confirmation.value, current_step="等待人工确认")
        return self.get_summary(run_id)

    @staticmethod
    def _auto_mode_enabled() -> bool:
        return settings.run_interaction_mode.strip().lower() == "auto"

    def _ensure_approval(self, run_id: str, request_type: str, task_id: str | None, title: str, message: str) -> bool:
        if self._approved(run_id, request_type, task_id):
            return True
        request = approval_service.ensure_pending(run_id, request_type, title, message, task_id=task_id)
        if self._auto_mode_enabled():
            approval_service.resolve(request["id"], True, resolved_by="system:auto")
            return True
        return False

    def _has_pending_approval(self, run_id: str) -> bool:
        return bool(ApprovalRequestRepository.get_by_run(run_id, status="pending"))

    def _approved(self, run_id: str, request_type: str, task_id: str | None = None) -> bool:
        approvals = ApprovalRequestRepository.get_by_run(run_id)
        return any(
            item["request_type"] == request_type
            and item.get("task_id") == task_id
            and item["status"] == "approved"
            for item in approvals
        )

    def _assert_not_cancelled(self, run_id: str):
        run = RunRepository.get_by_id(run_id)
        if run and run.get("status") in {RunStatus.cancelling.value, RunStatus.cancelled.value}:
            raise RunCancelled()

    def _cancel_now(self, run_id: str) -> dict:
        current = RunRepository.get_by_id(run_id)
        if current and current.get("status") == RunStatus.cancelled.value:
            return self.get_summary(run_id)
        RunRepository.update_status(run_id, RunStatus.cancelled.value, current_step="运行已取消", completed_at=datetime.now().isoformat())
        self._cancel_inflight_tasks(run_id)
        self._reset_agents(run_id)
        run_event_service.emit(run_id, "run.cancelled", "cancel", "运行已取消", "运行被用户取消")
        return self.get_summary(run_id)

    def _reset_agents(self, run_id: str, blocked: bool = False):
        status = "blocked" if blocked else "idle"
        tasks = TaskRepository.get_all(run_id=run_id)
        agent_ids = {task.get("owner_agent") for task in tasks if task.get("owner_agent")}
        for agent_id in agent_ids:
            AgentRepository.update_status(agent_id, status, 0.0, current_tasks=[])

    def _register_active_task(self, run_id: str) -> None:
        task = asyncio.current_task()
        if task:
            self._active_tasks[run_id] = task

    def _unregister_active_task(self, run_id: str) -> None:
        task = asyncio.current_task()
        if task and self._active_tasks.get(run_id) is task:
            self._active_tasks.pop(run_id, None)

    def _cancel_active_task(self, run_id: str) -> bool:
        task = self._active_tasks.get(run_id)
        if not task or task.done():
            return False
        task.cancel()
        return True

    def _cancel_inflight_tasks(self, run_id: str) -> None:
        terminal_statuses = {"completed", "failed", "archived"}
        for task in TaskRepository.get_all(run_id=run_id):
            if task.get("status") not in terminal_statuses:
                TaskRepository.update_status(task["id"], "blocked", blocked_reason="运行已取消")


run_execution_service = RunExecutionService()
