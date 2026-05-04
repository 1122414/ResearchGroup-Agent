import json
import uuid
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..models.run import RunStatus
from ..storage.repositories import RunRepository, TaskRepository, AgentRepository, SubAgentRepository
from ..services.task_decomposer import task_decomposer
from ..services.task_scheduler import task_scheduler
from ..services.task_executor import task_executor
from ..services.subagent_service import subagent_service
from ..services.review_service import review_service
from ..services.report_service import report_service


class RunCreateRequest(BaseModel):
    research_goal: str


router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("")
async def create_run(req: RunCreateRequest):
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    run = {
        "id": run_id,
        "research_goal": req.research_goal,
        "status": RunStatus.created.value,
        "current_step": "",
        "task_ids": [],
        "agent_assignments": {},
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
    }
    RunRepository.insert(run)
    return {"run_id": run_id, "status": "created"}


@router.get("/{run_id}")
async def get_run(run_id: str):
    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行不存在")
    tasks = TaskRepository.get_all(run_id=run_id)
    return {"run": run, "tasks": tasks}


@router.get("")
async def get_runs():
    runs = RunRepository.get_all()
    return {"runs": runs}


@router.post("/{run_id}/run_all")
async def run_all(run_id: str):
    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行不存在")

    try:
        # Step 1: 导师拆解任务
        RunRepository.update_status(run_id, "decomposing", current_step="任务拆解")
        tasks = await task_decomposer.decompose(run["research_goal"], run_id)
        RunRepository.update_status(run_id, "decomposing", task_ids=[t["id"] for t in tasks], current_step="任务拆解完成")

        # Step 2: 任务调度分配
        RunRepository.update_status(run_id, "scheduling", current_step="任务分配")
        assignments = task_scheduler.assign_all(tasks)
        RunRepository.update_status(run_id, "scheduling", agent_assignments=assignments, current_step="任务分配完成")

        # Step 3: 执行任务
        RunRepository.update_status(run_id, "executing", current_step="任务执行")
        for task in TaskRepository.get_all(run_id=run_id):
            if not task.get("owner_agent"):
                continue

            TaskRepository.update_status(task["id"], "running")

            # 尝试创建 SubAgent
            agent = AgentRepository.get_by_id(task["owner_agent"])
            if agent and subagent_service.can_create_subagent(task, agent):
                await subagent_service.create_and_execute(task["owner_agent"], task)

            # 执行主任务
            await task_executor.execute(task)

        # Step 4: 导师审核
        RunRepository.update_status(run_id, "reviewing", current_step="导师审核")
        for task in TaskRepository.get_all(run_id=run_id):
            if task.get("status") == "running" and task.get("outputs"):
                TaskRepository.update_status(task["id"], "waiting_review")
                review = await review_service.review(task)

        # Step 5: 生成报告
        RunRepository.update_status(run_id, "reporting", current_step="报告生成")
        updated_run = RunRepository.get_by_id(run_id)
        report = await report_service.generate(updated_run)

        # 完成
        now = datetime.now().isoformat()
        RunRepository.update_status(run_id, "completed", current_step="完成", completed_at=now)

        tasks_final = TaskRepository.get_all(run_id=run_id)
        completed_count = len([t for t in tasks_final if t.get("status") == "completed"])
        need_revision_count = len([t for t in tasks_final if t.get("status") == "need_revision"])

        return {
            "run_id": run_id,
            "status": "completed",
            "tasks_total": len(tasks_final),
            "tasks_completed": completed_count,
            "tasks_need_revision": need_revision_count,
            "report_available": True,
        }

    except Exception as e:
        RunRepository.update_status(run_id, "failed", current_step=f"失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"运行失败: {str(e)}")
