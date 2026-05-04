from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    created = "created"
    decomposing = "decomposing"
    scheduling = "scheduling"
    executing = "executing"
    reviewing = "reviewing"
    reporting = "reporting"
    completed = "completed"
    failed = "failed"


class Run(BaseModel):
    id: str
    research_goal: str
    status: RunStatus = RunStatus.created
    current_step: str = ""
    task_ids: list[str] = Field(default_factory=list)
    agent_assignments: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
