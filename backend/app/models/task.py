from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field
from .agent import SkillSet


class TaskStatus(str, Enum):
    pending = "pending"
    assigned = "assigned"
    running = "running"
    waiting_collab = "waiting_collab"
    waiting_subagent = "waiting_subagent"
    waiting_review = "waiting_review"
    need_revision = "need_revision"
    completed = "completed"
    archived = "archived"
    failed = "failed"


class TaskType(str, Enum):
    literature_survey = "literature_survey"
    system_design = "system_design"
    experiment_design = "experiment_design"
    result_analysis = "result_analysis"
    report_writing = "report_writing"


class TaskCreate(BaseModel):
    title: str
    description: str
    task_type: TaskType
    priority: int = Field(default=5, ge=1, le=10)
    complexity: int = Field(default=5, ge=1, le=10)
    decomposability: int = Field(default=5, ge=1, le=10)
    required_skills: SkillSet


class Task(BaseModel):
    id: str
    title: str
    description: str
    task_type: TaskType
    required_skills: SkillSet
    priority: int = Field(default=5, ge=1, le=10)
    complexity: int = Field(default=5, ge=1, le=10)
    decomposability: int = Field(default=5, ge=1, le=10)
    status: TaskStatus = TaskStatus.pending
    owner_agent: Optional[str] = None
    collaborator_agents: list[str] = Field(default_factory=list)
    subtasks: list[str] = Field(default_factory=list)
    outputs: list[dict] = Field(default_factory=list)
    review_result: Optional[dict] = None
    review_feedback: Optional[str] = None
    run_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class TaskTemplate(BaseModel):
    task_type: TaskType
    required_skills: SkillSet
    description_template: str = ""
