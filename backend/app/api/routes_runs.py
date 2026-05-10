import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from ..core.config import settings
from ..models.run import RunStatus
from ..services.run_event_service import run_event_service
from ..services.run_execution_service import run_execution_service
from ..storage.repositories import LLMUsageRepository, RunEventRepository, RunRepository, TaskRepository


import asyncio
import traceback

async def _safe_execute_run(run_id: str) -> None:
    await asyncio.sleep(0)
    try:
        await run_execution_service.execute(run_id)
    except Exception:
        traceback.print_exc()


class RunCreateRequest(BaseModel):
    research_goal: str


class CancelRequest(BaseModel):
    reason: str | None = None


router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("")
async def create_run(req: RunCreateRequest):
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    run = {
        "id": run_id,
        "research_goal": req.research_goal,
        "status": RunStatus.created.value,
        "current_step": "已创建，等待启动",
        "task_ids": [],
        "agent_assignments": {},
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "cancel_requested_at": None,
        "cancel_reason": None,
        "total_cost_usd": 0,
        "total_tokens": 0,
        "total_llm_calls": 0,
        "last_event_id": None,
    }
    RunRepository.insert(run)
    run_event_service.emit(run_id, "run.created", "run", "运行已创建", "等待用户启动执行")
    return {"run_id": run_id, "status": RunStatus.created.value}


@router.get("")
async def get_runs():
    return {"runs": RunRepository.get_all()}


@router.get("/{run_id}")
async def get_run(run_id: str):
    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行不存在")
    return {"run": run, "tasks": TaskRepository.get_all(run_id=run_id)}


@router.post("/{run_id}/start")
async def start_run(run_id: str, background_tasks: BackgroundTasks):
    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行不存在")
    if run.get("status") not in (RunStatus.created.value, RunStatus.queued.value):
        return {"status": run.get("status"), "message": "运行已在进行中或已完成"}

    started_at = datetime.now().isoformat()
    RunRepository.update_status(run_id, RunStatus.queued.value, current_step="等待执行", started_at=started_at)
    run_event_service.emit(run_id, "run.started", "run", "运行开始", "导师 Agent 开始处理研究目标")
    background_tasks.add_task(_safe_execute_run, run_id)
    return {"status": RunStatus.queued.value, "message": "运行已启动"}


@router.post("/{run_id}/run_all")
async def run_all(run_id: str):
    return await run_execution_service.execute(run_id)


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str, req: CancelRequest | None = None):
    reason = req.reason if req and req.reason else "用户请求停止运行"
    return {"run": run_execution_service.request_cancel(run_id, reason)}


@router.get("/{run_id}/summary")
async def get_run_summary(run_id: str):
    return run_execution_service.get_summary(run_id)


@router.get("/{run_id}/events")
async def get_run_events(
    run_id: str,
    limit: int = Query(default=settings.run_event_default_limit, ge=1),
    after_id: str | None = None,
    phase: str | None = None,
    task_id: str | None = None,
):
    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行不存在")
    safe_limit = min(limit, settings.run_event_max_limit)
    events = RunEventRepository.get_by_run(run_id, limit=safe_limit, after_id=after_id, phase=phase, task_id=task_id)
    return {"events": events, "next_after_id": events[-1]["id"] if events else after_id}


@router.get("/{run_id}/usage")
async def get_run_usage(run_id: str):
    run = RunRepository.get_by_id(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="运行不存在")
    return {"summary": LLMUsageRepository.get_summary(run_id), "items": LLMUsageRepository.get_by_run(run_id)}
