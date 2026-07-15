import asyncio
from datetime import datetime
from pathlib import Path

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
    TaskDependencyRepository,
    TaskRepository,
)
from .approval_service import approval_service
from .report_service import ReportGroundingError, ReportQualityError, report_service
from .research_contract_service import research_contract_service
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
from .thesis_chapter_service import thesis_chapter_service


class RunCancelled(Exception):
    pass


class RunExecutionService:
    TRANSIENT_WRITING_MAX_ATTEMPTS = 2

    def __init__(self) -> None:
        self._active_tasks: dict[str, asyncio.Task] = {}

    def recover_interrupted_runs(self) -> list[str]:
        """Resume persisted active runs after a backend process restart."""
        active_statuses = {
            RunStatus.queued.value, RunStatus.decomposing.value, RunStatus.scheduling.value,
            RunStatus.executing.value, RunStatus.reviewing.value, RunStatus.reporting.value,
        }
        recovered: list[str] = []
        for run in RunRepository.get_all():
            shutdown_cancelled = run.get("status") == RunStatus.cancelled.value and not run.get("cancel_reason")
            if (run.get("status") not in active_statuses and not shutdown_cancelled) or not self._has_owned_artifact(run):
                continue
            if len(recovered) >= max(1, settings.run_restart_recovery_limit):
                break
            run_id = run["id"]
            for task in TaskRepository.get_all(run_id=run_id):
                if task.get("status") not in {"running", "waiting_review"}:
                    continue
                status = "running" if task.get("outputs") else "pending"
                TaskRepository.update_status(
                    task["id"], status, blocked_reason="服务重启后从持久化检查点恢复",
                )
            RunRepository.update_status(
                run_id, RunStatus.executing.value, current_step="服务重启后恢复执行",
                completed_at=None, cancel_requested_at=None, cancel_reason=None,
            )
            run_event_service.emit(
                run_id, "run.recovered", "recovery", "运行已从服务重启恢复",
                "复用已持久化任务、审批、证据与检查点继续执行",
            )
            asyncio.create_task(self.execute(run_id))
            recovered.append(run_id)
        return recovered

    @staticmethod
    def _has_owned_artifact(run: dict) -> bool:
        try:
            path = Path(str(run.get("artifact_dir") or "")).resolve()
            root = settings.artifacts_dir.resolve()
            marker = path / ".run_id"
            return path.is_relative_to(root) and marker.is_file() and marker.read_text(encoding="utf-8").strip() == run["id"]
        except (OSError, KeyError):
            return False

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
                self._archive_superseded_revisions(run_id)

            if self._has_pending_approval(run_id):
                return self._pause_for_confirmation(run_id)

            self._assert_not_cancelled(run_id)
            await self._execute_research_flow(run_id)
            if self._has_pending_approval(run_id):
                return self._pause_for_confirmation(run_id)

            tasks = TaskRepository.get_all(run_id=run_id)
            research_tasks = [task for task in tasks if not thesis_chapter_service.is_writing_task(task)]
            if not self._research_settled(research_tasks):
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
                research_tasks = [task for task in tasks if not thesis_chapter_service.is_writing_task(task)]
                if not self._research_settled(research_tasks):
                    RunRepository.update_status(run_id, RunStatus.reviewing.value, current_step="等待下一轮研究任务完成")
                    return self.get_summary(run_id)

            loop_snapshot = research_loop_service.snapshot(run_id)
            if loop_snapshot["terminal_state"] in {"human_required", "incomplete"}:
                if not self._approved(run_id, "research_loop_intervention"):
                    approval_service.ensure_pending(
                        run_id,
                        "research_loop_intervention",
                        "研究闭环尚未达到论文质量线",
                        loop_snapshot["stop_reason"],
                        payload={
                            "terminal_state": loop_snapshot["terminal_state"],
                            "required_actions": loop_snapshot["human_requirements"],
                            "research_state": loop_snapshot["state"],
                        },
                    )
                    run_event_service.emit(
                        run_id, "research_loop.intervention_required", "research_loop", "需要人工补充研究条件",
                        loop_snapshot["stop_reason"], payload={"terminal_state": loop_snapshot["terminal_state"]},
                    )
                    return self._pause_for_confirmation(run_id)
                run_event_service.emit(
                    run_id,
                    "research_loop.intervention_accepted",
                    "research_loop",
                    "已接受研究边界并继续成文",
                    loop_snapshot["stop_reason"],
                    payload={
                        "terminal_state": loop_snapshot["terminal_state"],
                        "research_state": loop_snapshot["state"],
                    },
                )

            # If every research task failed there is nothing to write a report
            # from. Finalize the run as failed instead of producing an empty
            # report or stalling.
            settled_research = [
                task for task in TaskRepository.get_all(run_id=run_id)
                if not thesis_chapter_service.is_writing_task(task)
            ]
            if settled_research and all(task.get("status") == "failed" for task in settled_research):
                RunRepository.update_status(
                    run_id,
                    RunStatus.failed.value,
                    current_step="所有研究任务均失败，无法生成报告",
                    completed_at=datetime.now().isoformat(),
                )
                self._reset_agents(run_id, blocked=True)
                run_event_service.emit(run_id, "run.failed", "error", "运行失败", "所有研究任务均未通过审核或执行失败")
                return self.get_summary(run_id)

            chapter_tasks = thesis_chapter_service.ensure_tasks(run_id)
            if chapter_tasks:
                self._ensure_scheduling(TaskRepository.get_all(run_id=run_id), run_id)
                run_event_service.emit(
                    run_id, "thesis.chapters_created", "writing", "硕士论文章节任务已创建",
                    f"按冻结院校规范创建 {len(chapter_tasks)} 个章节任务",
                    payload={"task_ids": [item["id"] for item in chapter_tasks]},
                )
            for length_round in range(3):
                await self._execute_writing_flow(run_id)
                if self._has_pending_approval(run_id):
                    return self._pause_for_confirmation(run_id)

                tasks = TaskRepository.get_all(run_id=run_id)
                writing_tasks = [task for task in tasks if thesis_chapter_service.is_writing_task(task)]
                if writing_tasks and not self._research_settled(writing_tasks):
                    RunRepository.update_status(run_id, RunStatus.reviewing.value, current_step="等待写作任务完成或返工")
                    return self.get_summary(run_id)
                failed_chapters = self._failed_required_chapters(tasks)
                failed_chapters.extend(
                    task for task in self._invalid_required_chapters(run_id)
                    if task["id"] not in {item["id"] for item in failed_chapters}
                )
                if failed_chapters:
                    names = "、".join(task.get("title") or task["id"] for task in failed_chapters)
                    reason = f"必需论文章节未通过科学质量门：{names}"
                    RunRepository.update_status(
                        run_id, RunStatus.failed.value, current_step=reason,
                        completed_at=datetime.now().isoformat(),
                    )
                    self._reset_agents(run_id, blocked=True)
                    run_event_service.emit(
                        run_id, "thesis.assembly_blocked", "writing", "论文装配已阻断", reason,
                        payload={"failed_chapter_ids": [task["id"] for task in failed_chapters]},
                    )
                    return self.get_summary(run_id)
                adjustment = thesis_chapter_service.total_word_adjustment(run_id)
                if not adjustment:
                    break
                if length_round >= 2:
                    reason = "论文总字数经过两轮有界拟合后仍未进入冻结院校范围"
                    RunRepository.update_status(
                        run_id, RunStatus.failed.value, current_step=reason,
                        completed_at=datetime.now().isoformat(),
                    )
                    self._reset_agents(run_id, blocked=True)
                    return self.get_summary(run_id)
                reopened = task_recovery_service.reopen_for_thesis_length(adjustment["task"], adjustment)
                run_event_service.emit(
                    run_id, "thesis.length_adjustment", "writing", "论文总字数有界拟合",
                    f"{adjustment['direction']} {reopened['id']} 到约 {adjustment['target']} 词",
                    task_id=reopened["id"], payload={key: value for key, value in adjustment.items() if key != "task"},
                )

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
            try:
                await report_service.generate(updated_run)
            except (ReportGroundingError, ReportQualityError) as exc:
                approval_service.ensure_pending(
                    run_id, "report_revision_required", "最终报告质量门未通过", str(exc),
                    payload={"required_action": "查看 grounding/scientific quality gate artifact 并修复研究状态"},
                )
                run_event_service.emit(
                    run_id, "report.revision_required", "report", "报告发布已阻断", str(exc),
                )
                return self._pause_for_confirmation(run_id)
            run_event_service.emit(run_id, "report.created", "report", "最终报告已生成", "最终 Markdown 报告已写入 artifacts")
            completed_at = datetime.now().isoformat()
            RunRepository.update_status(run_id, RunStatus.completed.value, current_step="完成", completed_at=completed_at)
            self._reset_agents(run_id)
            run_event_service.emit(run_id, "run.completed", "run", "运行完成", "全部任务已归档，Agent 已回到空闲状态")
            return self.get_summary(run_id)
        except asyncio.CancelledError:
            current = RunRepository.get_by_id(run_id) or {}
            if current.get("status") in {RunStatus.cancelling.value, RunStatus.cancelled.value}:
                return self._cancel_now(run_id)
            RunRepository.update_status(
                run_id, RunStatus.reviewing.value,
                current_step="服务关闭，等待重启后从检查点恢复", completed_at=None,
            )
            run_event_service.emit(
                run_id, "run.interrupted", "recovery", "服务关闭，运行已持久化",
                "下次启动将复用现有任务、证据和审批继续执行",
            )
            return self.get_summary(run_id)
        except RunCancelled:
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
        RunRepository.update_status(run_id, RunStatus.decomposing.value, current_step="定义研究契约", started_at=started_at)
        contract = await research_contract_service.ensure_contract(run)
        if not contract["ready"]:
            approval_service.ensure_pending(
                run_id,
                "research_contract_revision",
                "研究契约或执行条件需要补充",
                "研究问题、方法论、资源或伦理条件尚未放行；补充前不会创建可能伪造完成状态的任务。",
                payload={
                    "validation_errors": contract["errors"], "brief": contract["brief"],
                    "feasibility_assessment": contract.get("assessment") or {},
                },
            )
            run_event_service.emit(
                run_id, "research_contract.blocked", "framing", "研究契约未通过",
                "；".join(contract["errors"]), payload={"validation_errors": contract["errors"]},
            )
            return []
        brief = contract["brief"]
        if brief.get("approval_status") != "frozen" and not self._ensure_approval(
            run_id,
            "research_contract_freeze",
            None,
            "冻结研究问题与完成判据",
            f"主问题：{brief.get('research_question', '')}；范围外：{'；'.join(brief.get('scope_out') or [])}",
        ):
            return []
        if brief.get("approval_status") != "frozen":
            brief = research_contract_service.freeze(run_id)
            contract["brief"] = brief
            run_event_service.emit(
                run_id, "research_contract.frozen", "framing", "研究契约已冻结",
                brief.get("research_question", ""), payload={
                    "research_type": brief.get("research_type"),
                    "discipline": brief.get("discipline"),
                    "methodology_family": brief.get("methodology_family"),
                    "epistemic_mode": brief.get("epistemic_mode"),
                    "master_thesis_ready": (brief.get("feasibility_assessment") or {}).get("thesis_ready"),
                },
            )
        RunRepository.update_status(run_id, RunStatus.decomposing.value, current_step="导师拆解研究任务", started_at=started_at)
        run_event_service.emit(run_id, "phase.started", "decompose", "导师拆解研究任务", "导师 Agent 生成任务图")
        tasks = await task_decomposer.decompose(run["research_goal"], run_id, contract)
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

    def _research_settled(self, tasks: list[dict]) -> bool:
        """A task group is settled when nothing can make further progress.

        Settled means every task is either in a terminal state
        (completed/failed/archived) or is blocked solely because its
        dependencies have failed and will never complete. In both cases the run
        must move on rather than stall in `reviewing` forever. Only a task that
        is actively runnable (running/waiting_review/need_revision or a ready
        task) keeps the group unsettled.
        """
        terminal = {"completed", "failed", "archived"}
        active = [task for task in tasks if task.get("status") not in terminal]
        if not active:
            return True
        all_run_tasks = TaskRepository.get_all(run_id=tasks[0]["run_id"]) if tasks else []
        ready_ids = {item["id"] for item in task_graph_service.ready_tasks(all_run_tasks)}
        status_map = {task["id"]: task.get("status") for task in all_run_tasks}
        for task in active:
            if task.get("status") in {"running", "waiting_review", "need_revision"}:
                return False
            if task["id"] in ready_ids:
                return False
            # A blocked task whose dependencies are still progressing (not yet
            # terminal) may still become runnable, so keep waiting.
            deps = TaskDependencyRepository.get_for_task(task["id"])
            if any(status_map.get(dep) not in terminal for dep in deps):
                return False
        return True

    @staticmethod
    def _failed_required_chapters(tasks: list[dict]) -> list[dict]:
        return [
            task for task in tasks
            if task.get("task_type") == "thesis_chapter"
            and not task.get("revision_of_task_id")
            and task.get("status") != "completed"
        ]

    @staticmethod
    def _invalid_required_chapters(run_id: str) -> list[dict]:
        return [
            task for task in thesis_chapter_service.resolved_chapters(run_id)
            if task.get("status") != "completed"
            or thesis_chapter_service.validate_output(task, (task.get("outputs") or [{}])[-1])
        ]

    @staticmethod
    def _archive_superseded_revisions(run_id: str) -> None:
        tasks = TaskRepository.get_all(run_id=run_id)
        completed_roots = {
            task.get("revision_of_task_id")
            for task in tasks
            if task.get("revision_of_task_id") and task.get("status") == "completed"
        }
        for task in tasks:
            if (
                task.get("revision_of_task_id") in completed_roots
                and task.get("status") not in {"completed", "failed", "archived"}
            ):
                TaskRepository.update_status(
                    task["id"],
                    "archived",
                    blocked_reason="已被同一返工链中通过审核的新版本取代。",
                )

    async def _execute_research_flow(self, run_id: str) -> None:
        while True:
            tasks = TaskRepository.get_all(run_id=run_id)
            research_tasks = [task for task in tasks if not thesis_chapter_service.is_writing_task(task)]
            if not research_tasks:
                return
            before = [(task["id"], task.get("status")) for task in research_tasks]
            RunRepository.update_status(run_id, RunStatus.executing.value, current_step="研究任务执行中")
            await self._execute_ready_tasks(run_id, research_tasks)
            await self._review_task_batch(run_id, research_tasks)
            if self._has_pending_approval(run_id):
                return
            refreshed = TaskRepository.get_all(run_id=run_id)
            latest_research = [task for task in refreshed if not thesis_chapter_service.is_writing_task(task)]
            if all(task.get("status") in {"completed", "failed"} for task in latest_research):
                return
            after = [(task["id"], task.get("status")) for task in latest_research]
            if after == before:
                # No task changed state this round. Before giving up, try to break
                # any revision dead-lock: tasks stuck in need_revision that can no
                # longer spawn a new revision must be finalized as failed so the run
                # can move on instead of silently stalling forever.
                if self._finalize_stuck_revisions(run_id, latest_research):
                    continue
                return

    def _finalize_stuck_revisions(self, run_id: str, tasks: list[dict]) -> bool:
        """Mark exhausted-revision tasks as failed to escape an orchestration stall.

        This is only invoked once a full execute+review round produced NO state
        change (a genuine stall). In that situation any task still sitting in
        need_revision can no longer make progress: if it could spawn another
        usable revision round, that round would have changed state this loop.
        So we finalize every such task as failed and unblock its root, letting
        the run proceed to its terminal state instead of hanging forever.

        Returns True if any task was finalized (caller should re-loop)."""
        changed = False
        for task in tasks:
            if task.get("status") != "need_revision":
                continue
            # Give the task one more chance only if a fresh revision round is
            # genuinely available (no live sibling, under the round cap). During
            # a stall a live sibling means that sibling is itself stuck, so we
            # finalize regardless to avoid an endless loop.
            terminal_feedback = (
                f"已达到最大返工轮次 {settings.task_max_revision_rounds}，"
                "审核仍未通过，系统终止该任务以避免运行卡死。"
            )
            TaskRepository.update_status(
                task["id"],
                "failed",
                blocked_reason=terminal_feedback,
                review_feedback=terminal_feedback,
            )
            run_event_service.emit(
                run_id,
                "revision.exhausted",
                "review",
                "返工轮次已耗尽",
                terminal_feedback,
                task_id=task["id"],
                agent_id=task.get("owner_agent"),
            )
            # Finalize the whole revision family (root + sibling revisions) so no
            # downstream dependent stays frozen waiting on a dead chain.
            root_id = task.get("revision_of_task_id") or task["id"]
            family_ids = {root_id} | {
                item["id"]
                for item in TaskRepository.get_all(run_id=run_id)
                if item.get("revision_of_task_id") == root_id
            }
            for fid in family_ids:
                member = TaskRepository.get_by_id(fid)
                if member and member.get("status") not in {"completed", "failed", "archived"}:
                    TaskRepository.update_status(
                        fid,
                        "failed",
                        blocked_reason=terminal_feedback,
                        review_feedback=terminal_feedback,
                    )
            self._fail_dependency_descendants(run_id, root_id, terminal_feedback)
            changed = True
        return changed

    @staticmethod
    def _fail_dependency_descendants(run_id: str, root_task_id: str, reason: str) -> None:
        for task_id in task_graph_service.descendants(run_id, root_task_id):
            task = TaskRepository.get_by_id(task_id)
            if task and task.get("status") not in {"completed", "failed", "archived"}:
                TaskRepository.update_status(
                    task_id,
                    "failed",
                    blocked_reason=f"前置任务失败，无法继续：{reason}",
                    review_feedback=f"前置任务失败，无法继续：{reason}",
                )

    async def _execute_writing_flow(self, run_id: str) -> None:
        while True:
            tasks = TaskRepository.get_all(run_id=run_id)
            writing_tasks = [task for task in tasks if thesis_chapter_service.is_writing_task(task)]
            if not writing_tasks:
                return
            self._retry_transient_writing_failures(writing_tasks)
            writing_tasks = [
                task for task in TaskRepository.get_all(run_id=run_id)
                if thesis_chapter_service.is_writing_task(task)
            ]
            before = [(task["id"], task.get("status")) for task in writing_tasks]
            RunRepository.update_status(run_id, RunStatus.executing.value, current_step="论文章节与总稿写作中")
            await self._execute_ready_tasks(run_id, writing_tasks)
            await self._review_task_batch(run_id, writing_tasks)
            if self._has_pending_approval(run_id):
                return
            refreshed = [
                task for task in TaskRepository.get_all(run_id=run_id)
                if thesis_chapter_service.is_writing_task(task)
            ]
            if all(task.get("status") in {"completed", "failed", "archived"} for task in refreshed):
                return
            after = [(task["id"], task.get("status")) for task in refreshed]
            if after == before:
                self._finalize_stuck_revisions(run_id, refreshed)
                return

    def _retry_transient_writing_failures(self, tasks: list[dict]) -> bool:
        changed = False
        for task in tasks:
            if (
                task.get("status") == "failed"
                and int(task.get("attempt_count") or 0) < self.TRANSIENT_WRITING_MAX_ATTEMPTS
                and "structured output invalid" in str(task.get("blocked_reason") or "")
            ):
                task_recovery_service.retry(task, reason="写作 JSON 结构瞬态失败，执行一次有界重试")
                run_event_service.emit(
                    task["run_id"], "task.transient_retry", "recovery", "写作任务结构修复重试",
                    "仅重试一次完整写作调用；科学质量门保持不变", task_id=task["id"],
                    agent_id=task.get("owner_agent"),
                )
                changed = True
        return changed

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
        if str(task.get("title") or "").startswith("[循环R"):
            usage = research_loop_service._loop_usage_summary(run_id)
            if (
                usage["total_tokens"] >= settings.research_loop_max_tokens
                or usage["total_cost_usd"] >= settings.research_loop_max_cost_usd
            ):
                reason = "研究循环预算已耗尽，动作未执行并转人工"
                TaskRepository.update_status(task["id"], "failed", blocked_reason=reason)
                run_event_service.emit(
                    run_id, "research_loop.budget_blocked", "research_loop", "研究动作被预算硬门阻止",
                    reason, task_id=task["id"], agent_id=owner, payload=usage,
                )
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
            execution = task_executor.execute(latest_task)
            if str(task.get("title") or "").startswith("[循环R"):
                await asyncio.wait_for(execution, timeout=settings.research_loop_action_timeout_seconds)
            else:
                await execution
            self._assert_not_cancelled(run_id)
            task_recovery_service.complete_attempt(task["id"], attempt["id"], checkpoint="task_output_created")
            run_event_service.emit(run_id, "task.output_created", "execute", "任务输出已生成", task.get("title", ""), task_id=task["id"], agent_id=owner)
        except Exception as exc:
            logger.error("[RunExecution] task failed | task_id=%s | error=%s", task["id"], exc, exc_info=True)
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
                    revision_task = task_recovery_service.create_revision_task(latest_after_review, review)
                    if not revision_task:
                        terminal_feedback = (
                            f"已达到最大返工轮次 {settings.task_max_revision_rounds}，"
                            "系统停止继续生成返工任务，请先补充检索能力或调整任务边界。"
                        )
                        TaskRepository.update_status(
                            latest_after_review["id"],
                            "failed",
                            blocked_reason=terminal_feedback,
                            review_feedback=terminal_feedback,
                        )
                        root_task_id = latest_after_review.get("revision_of_task_id") or latest_after_review["id"]
                        self._fail_dependency_descendants(run_id, root_task_id, terminal_feedback)
                        run_event_service.emit(
                            run_id,
                            "revision.exhausted",
                            "review",
                            "返工轮次已耗尽",
                            terminal_feedback,
                            task_id=task["id"],
                            agent_id=latest_task.get("owner_agent"),
                        )
                        continue
                    if review.get("review_mode") == "insufficient_evidence_guardrail":
                        request = approval_service.ensure_grouped_pending(
                            run_id,
                            "revision_required",
                            "revision_required:insufficient_evidence_guardrail",
                            "导师要求返工",
                            review.get("feedback", "导师要求补充修改后重做"),
                            task_id=task["id"],
                            revision_task_id=revision_task["id"],
                            task_title=latest_after_review.get("title", task["id"]),
                        )
                    else:
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
        requires_human = request_type == "experiment_execute" and settings.experiment_require_review
        if self._auto_mode_enabled() and not requires_human:
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
