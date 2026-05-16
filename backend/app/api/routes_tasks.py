import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from ..core.logger import logger
from ..models.run import RunStatus
from ..services.approval_service import approval_service
from ..services.run_event_service import run_event_service
from ..services.run_execution_service import run_execution_service
from ..services.task_graph_service import task_graph_service
from ..services.task_recovery_service import task_recovery_service
from ..storage.repositories import RunRepository, TaskRepository

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

DEFAULT_REQUIRED_SKILLS = {
    "literature_survey": {"literature_review": 8, "coding": 1, "experiment": 1, "data_analysis": 2, "academic_writing": 5, "mentoring": 1},
    "system_design": {"literature_review": 2, "coding": 8, "experiment": 4, "data_analysis": 4, "academic_writing": 2, "mentoring": 2},
    "experiment_design": {"literature_review": 3, "coding": 3, "experiment": 8, "data_analysis": 5, "academic_writing": 4, "mentoring": 2},
    "result_analysis": {"literature_review": 2, "coding": 4, "experiment": 3, "data_analysis": 9, "academic_writing": 5, "mentoring": 2},
    "report_writing": {"literature_review": 5, "coding": 1, "experiment": 2, "data_analysis": 4, "academic_writing": 9, "mentoring": 3},
}


class DependencyUpdateRequest(BaseModel):
    depends_on_task_ids: list[str] = Field(default_factory=list)


class TaskActionRequest(BaseModel):
    reason: str = ""


class TaskCreateRequest(BaseModel):
    run_id: str
    title: str
    description: str = ""
    task_type: str
    required_skills: dict[str, int] = Field(default_factory=dict)
    priority: int = 5
    complexity: int = 5
    decomposability: int = 5
    parallelizable: bool = True
    depends_on_task_ids: list[str] = Field(default_factory=list)


def _resume_run_if_needed(run_id: str, background_tasks: BackgroundTasks, current_step: str):
    run = RunRepository.get_by_id(run_id)
    if run and run.get("status") in {RunStatus.failed.value, RunStatus.waiting_confirmation.value, RunStatus.reviewing.value}:
        RunRepository.update_status(run["id"], RunStatus.executing.value, current_step=current_step)
        background_tasks.add_task(run_execution_service.execute, run["id"])


@router.get("")
async def get_tasks(run_id: str | None = None):
    logger.debug("[API] get_tasks | run_id=%s", run_id)
    return {"tasks": TaskRepository.get_all(run_id=run_id)}


@router.post("")
async def create_task(body: TaskCreateRequest):
    if not RunRepository.get_by_id(body.run_id):
        raise HTTPException(status_code=404, detail="运行不存在")
    now = datetime.now().isoformat()
    task = {
        "id": f"task_manual_{uuid.uuid4().hex[:8]}",
        "title": body.title,
        "description": body.description,
        "task_type": body.task_type,
        "required_skills": body.required_skills or DEFAULT_REQUIRED_SKILLS.get(body.task_type, {}),
        "priority": body.priority,
        "complexity": body.complexity,
        "decomposability": body.decomposability,
        "status": "pending",
        "owner_agent": None,
        "collaborator_agents": [],
        "subtasks": [],
        "outputs": [],
        "review_result": None,
        "review_feedback": None,
        "run_id": body.run_id,
        "assignment_info": {},
        "subagent_triggered": False,
        "blocked_reason": None,
        "parallelizable": body.parallelizable,
        "is_critical_path": False,
        "attempt_count": 0,
        "last_checkpoint": None,
        "revision_of_task_id": None,
        "created_at": now,
        "updated_at": now,
    }
    TaskRepository.insert(task)
    if body.depends_on_task_ids:
        task_graph_service.set_dependencies(task["id"], body.depends_on_task_ids)
    task_graph_service.recompute_critical_path(body.run_id)
    run_event_service.emit(body.run_id, "task.created", "manage", "手动补充任务", body.title, task_id=task["id"])
    return {"task": TaskRepository.get_by_id(task["id"]), "graph": task_graph_service.get_graph(body.run_id)}


@router.get("/{task_id}")
async def get_task(task_id: str):
    logger.debug("[API] get_task | task_id=%s", task_id)
    task = TaskRepository.get_by_id(task_id)
    if not task:
        logger.warning("[API] get_task | task_id=%s not found", task_id)
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"task": task}


@router.patch("/{task_id}/dependencies")
async def update_dependencies(task_id: str, body: DependencyUpdateRequest):
    return task_graph_service.set_dependencies(task_id, body.depends_on_task_ids)


@router.post("/{task_id}/retry")
async def retry_task(task_id: str, background_tasks: BackgroundTasks, body: TaskActionRequest | None = None):
    task = TaskRepository.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    action = task_recovery_service.retry(task, reason=(body.reason if body else "manual_retry"))
    _resume_run_if_needed(task["run_id"], background_tasks, "重试任务")
    return {"task": TaskRepository.get_by_id(task_id), "recovery_action": action}


@router.post("/{task_id}/resume")
async def resume_task(task_id: str, background_tasks: BackgroundTasks, body: TaskActionRequest | None = None):
    task = TaskRepository.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    action = task_recovery_service.resume_from_checkpoint(task, reason=(body.reason if body else "manual_resume"))
    _resume_run_if_needed(task["run_id"], background_tasks, "从检查点恢复")
    return {"task": TaskRepository.get_by_id(task_id), "recovery_action": action}


@router.post("/{task_id}/rerun-branch")
async def rerun_branch(task_id: str, background_tasks: BackgroundTasks, body: TaskActionRequest | None = None):
    task = TaskRepository.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    action = task_recovery_service.rerun_branch(task, reason=(body.reason if body else "manual_rerun_branch"))
    _resume_run_if_needed(task["run_id"], background_tasks, "重跑失败分支")
    return {"task": TaskRepository.get_by_id(task_id), "recovery_action": action}


@router.post("/{task_id}/approve")
async def approve_task(task_id: str, body: TaskActionRequest | None = None):
    task = TaskRepository.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    TaskRepository.update_status(task_id, "completed", blocked_reason=None)
    return {"task": TaskRepository.get_by_id(task_id), "message": body.reason if body else ""}


@router.post("/{task_id}/request-revision")
async def request_revision(task_id: str, body: TaskActionRequest | None = None):
    task = TaskRepository.get_by_id(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    feedback = body.reason if body and body.reason else (task.get("review_feedback") or "导师要求补充返工内容。")
    revision_task = task_recovery_service.create_revision_task(task, feedback)
    request = approval_service.ensure_pending(
        task["run_id"],
        "revision_required",
        "导师要求返工",
        feedback,
        task_id=task_id,
        payload={"revision_task_id": revision_task["id"]},
    )
    return {"task": TaskRepository.get_by_id(task_id), "revision_task": revision_task, "approval_request": request}
