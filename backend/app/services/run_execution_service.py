from datetime import datetime

from fastapi import HTTPException

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
        run = RunRepository.get_by_id(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="运行不存在")

        try:
            started_at = datetime.now().isoformat()
            RunRepository.update_status(run_id, RunStatus.decomposing.value, current_step="开始拆解任务", started_at=started_at)
            run_event_service.emit(run_id, "run.started", "run", "运行开始", "导师 Agent 开始处理研究目标")

            self._assert_not_cancelled(run_id)
            run_event_service.emit(run_id, "phase.started", "decompose", "开始拆解任务", "导师正在把研究目标拆成任务")
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
            RunRepository.update_status(run_id, RunStatus.scheduling.value, current_step="开始调度分配")
            run_event_service.emit(run_id, "phase.started", "schedule", "开始调度分配", "调度器正在根据技能和负载分配任务")
            assignments = task_scheduler.assign_all(tasks)
            RunRepository.update_status(run_id, RunStatus.scheduling.value, agent_assignments=assignments, current_step="调度分配完成")
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
            run_event_service.emit(run_id, "phase.completed", "schedule", "调度分配完成", "任务负责人和协作者已确定")

            self._assert_not_cancelled(run_id)
            RunRepository.update_status(run_id, RunStatus.executing.value, current_step="开始执行任务")
            run_event_service.emit(run_id, "phase.started", "execute", "开始执行任务", "研究生 Agent 开始处理任务")
            for task in TaskRepository.get_all(run_id=run_id):
                self._assert_not_cancelled(run_id)
                owner = task.get("owner_agent")
                if not owner:
                    continue
                TaskRepository.update_status(task["id"], "running")
                run_event_service.emit(run_id, "task.started", "execute", "任务开始执行", task.get("title", ""), task_id=task["id"], agent_id=owner)

                agent = AgentRepository.get_by_id(owner)
                if agent and subagent_service.can_create_subagent(task, agent):
                    self._assert_not_cancelled(run_id)
                    run_event_service.emit(run_id, "subagent.created", "subagent", "SubAgent 已触发", "任务复杂且可拆解，创建临时 SubAgent", task_id=task["id"], agent_id=owner)
                    await subagent_service.create_and_execute(owner, task)
                    run_event_service.emit(run_id, "subagent.completed", "subagent", "SubAgent 已完成", "结果已交回父 Agent", task_id=task["id"], agent_id=owner)

                self._assert_not_cancelled(run_id)
                latest_task = TaskRepository.get_by_id(task["id"]) or task
                await task_executor.execute(latest_task)
                run_event_service.emit(run_id, "task.output_created", "execute", "任务产出已生成", task.get("title", ""), task_id=task["id"], agent_id=owner)
            run_event_service.emit(run_id, "phase.completed", "execute", "任务执行完成", "进入导师审核阶段")

            self._assert_not_cancelled(run_id)
            RunRepository.update_status(run_id, RunStatus.reviewing.value, current_step="导师审核")
            run_event_service.emit(run_id, "phase.started", "review", "导师审核开始", "导师正在检查任务产出")
            for task in TaskRepository.get_all(run_id=run_id):
                self._assert_not_cancelled(run_id)
                if task.get("status") == "running" and task.get("outputs"):
                    TaskRepository.update_status(task["id"], "waiting_review")
                    run_event_service.emit(run_id, "review.started", "review", "开始审核任务", task.get("title", ""), task_id=task["id"], agent_id=task.get("owner_agent"))
                    review = await review_service.review(task)
                    run_event_service.emit(run_id, "review.completed", "review", "审核完成", review.get("feedback", ""), task_id=task["id"], agent_id=task.get("owner_agent"), payload=review)
            run_event_service.emit(run_id, "phase.completed", "review", "导师审核完成", "进入报告生成阶段")

            self._assert_not_cancelled(run_id)
            RunRepository.update_status(run_id, RunStatus.reporting.value, current_step="生成报告")
            run_event_service.emit(run_id, "phase.started", "report", "开始生成报告", "导师正在整理阶段性报告")
            updated_run = RunRepository.get_by_id(run_id)
            await report_service.generate(updated_run)
            run_event_service.emit(run_id, "report.created", "report", "报告已生成", "最终报告已写入输出中心和 artifacts")

            completed_at = datetime.now().isoformat()
            RunRepository.update_status(run_id, RunStatus.completed.value, current_step="完成", completed_at=completed_at)
            self._reset_agents(run_id)
            run_event_service.emit(run_id, "run.completed", "run", "运行完成", "所有阶段已结束")
            return self.get_summary(run_id)

        except RunCancelled:
            RunRepository.update_status(run_id, RunStatus.cancelled.value, current_step="已停止", completed_at=datetime.now().isoformat())
            self._reset_agents(run_id)
            run_event_service.emit(run_id, "run.cancelled", "cancel", "运行已停止", "用户请求停止后，系统已停止后续任务")
            return self.get_summary(run_id)
        except Exception as exc:
            RunRepository.update_status(run_id, RunStatus.failed.value, current_step=f"失败: {exc}", completed_at=datetime.now().isoformat())
            self._reset_agents(run_id, blocked=True)
            run_event_service.emit(run_id, "run.failed", "error", "运行失败", str(exc))
            raise

    def request_cancel(self, run_id: str, reason: str = "用户从前端请求停止") -> dict:
        run = RunRepository.get_by_id(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="运行不存在")
        if run.get("status") in (RunStatus.completed.value, RunStatus.failed.value, RunStatus.cancelled.value):
            return run
        RunRepository.update_status(
            run_id,
            RunStatus.cancelling.value,
            current_step="正在停止",
            cancel_requested_at=datetime.now().isoformat(),
            cancel_reason=reason,
        )
        run_event_service.emit(run_id, "run.cancel_requested", "cancel", "收到停止请求", reason)
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
            raise RunCancelled()

    def _reset_agents(self, run_id: str, blocked: bool = False):
        status = "blocked" if blocked else "idle"
        tasks = TaskRepository.get_all(run_id=run_id)
        agent_ids = {task.get("owner_agent") for task in tasks if task.get("owner_agent")}
        for agent_id in agent_ids:
            AgentRepository.update_status(agent_id, status, 0.0, current_tasks=[])


run_execution_service = RunExecutionService()
