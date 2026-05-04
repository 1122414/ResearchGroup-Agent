from fastapi import APIRouter, HTTPException
from ..storage.repositories import TaskRepository

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
async def get_tasks(run_id: str | None = None):
    tasks = TaskRepository.get_all(run_id=run_id)
    return {"tasks": tasks}


@router.get("/{task_id}")
async def get_task(task_id: str):
    task = TaskRepository.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"task": task}
