from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    created = "created"
    queued = "queued"
    decomposing = "decomposing"
    scheduling = "scheduling"
    executing = "executing"
    reviewing = "reviewing"
    reporting = "reporting"
    cancelling = "cancelling"
    cancelled = "cancelled"
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
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    cancel_requested_at: Optional[str] = None
    cancel_reason: Optional[str] = None
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    total_llm_calls: int = 0
    last_event_id: Optional[str] = None
