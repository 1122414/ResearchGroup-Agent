from typing import Literal

from pydantic import BaseModel, Field


class TaskDependency(BaseModel):
    task_id: str
    depends_on_task_id: str
    dependency_type: Literal["hard"] = "hard"


class TaskAttempt(BaseModel):
    id: str
    run_id: str
    task_id: str
    attempt_number: int = 1
    status: Literal["running", "completed", "failed"] = "running"
    failure_type: str | None = None
    failure_message: str | None = None
    checkpoint: str | None = None
    started_at: str
    completed_at: str | None = None


class RecoveryAction(BaseModel):
    id: str
    run_id: str
    task_id: str
    action_type: Literal["retry", "resume_checkpoint", "rerun_branch"]
    status: Literal["requested", "completed"] = "requested"
    reason: str = ""
    payload: dict = Field(default_factory=dict)
    created_at: str


class ApprovalRequest(BaseModel):
    id: str
    run_id: str
    task_id: str | None = None
    request_type: Literal[
        "experiment_execute", "revision_required", "report_publish", "research_loop_intervention",
        "report_revision_required",
    ]
    status: Literal["pending", "approved", "rejected"] = "pending"
    title: str
    message: str = ""
    payload: dict = Field(default_factory=dict)
    created_at: str
    resolved_at: str | None = None
    resolved_by: str | None = None
