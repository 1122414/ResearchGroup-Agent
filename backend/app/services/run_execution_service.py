from datetime import datetime

from fastapi import HTTPException

from ..core.logger import logger
from ..models.run import RunStatus
from ..storage.repositories import AgentRepository, LLMUsageRepository, RunEventRepository, RunRepository, SubAgentRepository, TaskRepository
from .report_service import report_service
from .review_service import review_service
from .run_event_service import run_event_service
from .subagent_service import subagent_service
from .task_decomposer import task_decomposer
from .task_executor import task_executor
from .task_scheduler import task_scheduler


class RunCancelled(Exception):
    pass


class RunExecutionService:
    async def execute(self, run_id: str) -> dict:
        logger.info("[RunExecution] execute started | run_id=%s", run_id)
        run = RunRepository.get_by_id(run_id)
        if not run:
            logger.error("[RunExecution] execute | run_id=%s not found", run_id)
            raise HTTPException(status_code=404, detail="运行不存在")
        if run.get("status") in (RunStatus.cancelling.value, RunStatus.cancelled.value):
            RunRepository.update_status(run_id, RunStatus.cancelled.value, current_step="运行已取消", completed_at=datetime.now().isoformat())
            run_event_service.emit(run_id, "run.cancelled", "cancel", "运行已取消", "运行在开始前已取消")
            return self.get_summary(run_id)

        try:
            current_status = run.get("status")
            if current_status == RunStatus.created.value:
                started_at = datetime.now().isoformat()
                RunRepository.update_status(run_id, RunStatus.decomposing.value, current_step="导师拆解研究任务", started_at=started_at)
                run_event_service.emit(run_id, "run.started", "run", "运行开始", "导师 Agent 开始拆解研究目标")
            else:
                RunRepository.update_status(run_id, RunStatus.decomposing.value, current_step="导师拆解研究任务")

            self._assert_not_cancelled(run_id)
            run_event_service.emit(run_id, "phase.started", "decompose", "导师拆解研究任务", "导师 Agent 正在把研究目标拆成可执行任务")
            tasks = await task_decomposer.decompose(run["research_goal"], run_id)
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

            self._assert_not_cancelled(run_id)
            RunRepository.update_status(run_id, RunStatus.scheduling.value, current_step="调度研究生 Agent")
            run_event_service.emit(run_id, "phase.started", "schedule", "调度研究生 Agent", "调度器按能力矩阵分配任务")
            assignments = task_scheduler.assign_all(tasks)
            RunRepository.update_status(run_id, RunStatus.scheduling.value, agent_assignments=assignments, current_step="任务调度完成")
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
            run_event_service.emit(run_id, "phase.completed", "schedule", "任务调度完成", "所有任务已分配到合适的 Agent")

            all_tasks = TaskRepository.get_all(run_id=run_id)
            research_tasks = [task for task in all_tasks if task.get("task_type") != "report_writing"]
            writing_tasks = [task for task in all_tasks if task.get("task_type") == "report_writing"]

            self._assert_not_cancelled(run_id)
            RunRepository.update_status(run_id, RunStatus.executing.value, current_step="研究生 Agent 执行调研任务")
            run_event_service.emit(run_id, "phase.started", "execute", "研究任务执行", "先执行调研、实验、分析、工程类任务")
            await self._execute_task_batch(run_id, research_tasks)
            run_event_service.emit(run_id, "phase.completed", "execute", "研究任务执行完成", "前置研究任务已生成产出")

            self._assert_not_cancelled(run_id)
            RunRepository.update_status(run_id, RunStatus.reviewing.value, current_step="导师审核研究任务")
            run_event_service.emit(run_id, "phase.started", "review", "导师审核研究任务", "导师 Agent 审核前置研究任务产出")
            await self._review_task_batch(run_id, research_tasks)
            run_event_service.emit(run_id, "phase.completed", "review", "研究任务审核完成", "前置研究产出已完成审核")

            if writing_tasks:
                self._assert_not_cancelled(run_id)
                RunRepository.update_status(run_id, RunStatus.executing.value, current_step="写作研究生整合最终报告素材")
                run_event_service.emit(run_id, "phase.started", "write", "写作研究生开始最终写作", "写作任务等待调研任务审核后才启动")
                await self._execute_task_batch(run_id, writing_tasks)
                await self._review_task_batch(run_id, writing_tasks)
                run_event_service.emit(run_id, "phase.completed", "write", "写作任务完成", "写作研究生已完成报告草稿并经过导师审核")

            self._assert_not_cancelled(run_id)
            RunRepository.update_status(run_id, RunStatus.reporting.value, current_step="生成最终研究报告")
            run_event_service.emit(run_id, "phase.started", "report", "生成最终研究报告", "写作研究生汇总全部调研产出，导师 Agent 审核定稿")
            updated_run = RunRepository.get_by_id(run_id)
            await report_service.generate(updated_run)
            run_event_service.emit(run_id, "report.created", "report", "最终报告已生成", "最终 Markdown 报告与导师审核汇总已写入 artifacts")

            completed_at = datetime.now().isoformat()
            RunRepository.update_status(run_id, RunStatus.completed.value, current_step="完成", completed_at=completed_at)
            self._reset_agents(run_id)
            run_event_service.emit(run_id, "run.completed", "run", "运行完成", "全部任务已归档，Agent 已回到待命状态")
            summary = self.get_summary(run_id)
            logger.info(
                "[RunExecution] execute completed | run_id=%s | status=%s | tasks=%d | agents=%d",
                run_id,
                summary.get("run", {}).get("status"),
                summary.get("counts", {}).get("tasks_total", 0),
                len(summary.get("agents", [])),
            )
            return summary

        except RunCancelled:
            RunRepository.update_status(run_id, RunStatus.cancelled.value, current_step="运行已取消", completed_at=datetime.now().isoformat())
            self._reset_agents(run_id)
            run_event_service.emit(run_id, "run.cancelled", "cancel", "运行已取消", "取消请求已处理，Agent 已回到待命状态")
            logger.info("[RunExecution] execute cancelled | run_id=%s", run_id)
            return self.get_summary(run_id)
        except Exception as exc:
            RunRepository.update_status(run_id, RunStatus.failed.value, current_step=f"执行失败: {exc}", completed_at=datetime.now().isoformat())
            self._reset_agents(run_id, blocked=True)
            run_event_service.emit(run_id, "run.failed", "error", "运行失败", str(exc))
            logger.error("[RunExecution] execute failed | run_id=%s | error=%s", run_id, exc, exc_info=True)
            raise

    async def _execute_task_batch(self, run_id: str, tasks: list[dict]) -> None:
        for task in tasks:
            self._assert_not_cancelled(run_id)
            owner = task.get("owner_agent")
            if not owner:
                logger.warning("[RunExecution] task has no owner | run_id=%s | task_id=%s", run_id, task["id"])
                continue

            TaskRepository.update_status(task["id"], "running")
            run_event_service.emit(run_id, "task.started", "execute", "任务开始执行", task.get("title", ""), task_id=task["id"], agent_id=owner)

            agent = AgentRepository.get_by_id(owner)
            if agent and subagent_service.can_create_subagent(task, agent):
                self._assert_not_cancelled(run_id)
                TaskRepository.update_status(task["id"], "running", subagent_triggered=True)
                run_event_service.emit(run_id, "subagent.created", "subagent", "SubAgent 已创建", "任务复杂度触发临时协作", task_id=task["id"], agent_id=owner)
                await subagent_service.create_and_execute(owner, task)
                run_event_service.emit(run_id, "subagent.completed", "subagent", "SubAgent 已完成", "临时协作结果已回交给研究生 Agent", task_id=task["id"], agent_id=owner)

            self._assert_not_cancelled(run_id)
            latest_task = TaskRepository.get_by_id(task["id"]) or task
            await task_executor.execute(latest_task)
            run_event_service.emit(run_id, "task.output_created", "execute", "任务产出已生成", task.get("title", ""), task_id=task["id"], agent_id=owner)

    async def _review_task_batch(self, run_id: str, tasks: list[dict]) -> None:
        for task in tasks:
            self._assert_not_cancelled(run_id)
            latest_task = TaskRepository.get_by_id(task["id"]) or task
            if latest_task.get("status") == "running" and latest_task.get("outputs"):
                TaskRepository.update_status(task["id"], "waiting_review")
                run_event_service.emit(run_id, "review.started", "review", "导师开始审核", latest_task.get("title", ""), task_id=task["id"], agent_id=latest_task.get("owner_agent"))
                review = await review_service.review(latest_task)
                run_event_service.emit(run_id, "review.completed", "review", "导师审核完成", review.get("feedback", ""), task_id=task["id"], agent_id=latest_task.get("owner_agent"), payload=review)

    def request_cancel(self, run_id: str, reason: str = "用户取消运行") -> dict:
        logger.info("[RunExecution] request_cancel | run_id=%s | reason=%s", run_id, reason)
        run = RunRepository.get_by_id(run_id)
        if not run:
            logger.warning("[RunExecution] request_cancel | run_id=%s not found", run_id)
            raise HTTPException(status_code=404, detail="运行不存在")
        if run.get("status") in (RunStatus.completed.value, RunStatus.failed.value, RunStatus.cancelled.value):
            logger.info("[RunExecution] request_cancel | run_id=%s already in final status=%s", run_id, run.get("status"))
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
            run_event_service.emit(run_id, "run.cancel_requested", "cancel", "取消运行", reason)
            run_event_service.emit(run_id, "run.cancelled", "cancel", "运行已取消", "运行尚未进入执行阶段，已直接取消")
            return RunRepository.get_by_id(run_id)
        RunRepository.update_status(
            run_id,
            RunStatus.cancelling.value,
            current_step="正在取消",
            cancel_requested_at=datetime.now().isoformat(),
            cancel_reason=reason,
        )
        run_event_service.emit(run_id, "run.cancel_requested", "cancel", "取消运行", reason)
        return RunRepository.get_by_id(run_id)

    def get_summary(self, run_id: str) -> dict:
        run = RunRepository.get_by_id(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="运行不存在")
        tasks = TaskRepository.get_all(run_id=run_id)
        agents = AgentRepository.get_all()
        subagents = SubAgentRepository.get_by_run(run_id)
        usage = LLMUsageRepository.get_summary(run_id)
        counts = {
            "tasks_total": len(tasks),
            "tasks_pending": len([task for task in tasks if task.get("status") == "pending"]),
            "tasks_running": len([task for task in tasks if task.get("status") == "running"]),
            "tasks_completed": len([task for task in tasks if task.get("status") == "completed"]),
            "tasks_need_revision": len([task for task in tasks if task.get("status") == "need_revision"]),
            "tasks_failed": len([task for task in tasks if task.get("status") == "failed"]),
            "subagents_total": len(subagents),
        }
        return {
            "run": run,
            "counts": counts,
            "usage": usage,
            "latest_event": RunEventRepository.get_latest(run_id),
            "tasks": tasks,
            "agents": agents,
        }

    def _assert_not_cancelled(self, run_id: str):
        run = RunRepository.get_by_id(run_id)
        if run and run.get("status") == RunStatus.cancelling.value:
            logger.info("[RunExecution] run cancelled detected | run_id=%s", run_id)
            raise RunCancelled()

    def _reset_agents(self, run_id: str, blocked: bool = False):
        status = "blocked" if blocked else "idle"
        tasks = TaskRepository.get_all(run_id=run_id)
        agent_ids = {task.get("owner_agent") for task in tasks if task.get("owner_agent")}
        for agent_id in agent_ids:
            AgentRepository.update_status(agent_id, status, 0.0, current_tasks=[])
        logger.info("[RunExecution] agents reset | run_id=%s | status=%s | count=%d", run_id, status, len(agent_ids))


run_execution_service = RunExecutionService()
