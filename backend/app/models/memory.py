from typing import Literal

from pydantic import BaseModel, Field


class MemoryRecord(BaseModel):
    id: str
    run_id: str
    agent_id: str | None = None
    scope: Literal["project", "agent"]
    category: str
    summary: str
    payload: dict = Field(default_factory=dict)
    source_task_id: str | None = None
    created_at: str
    updated_at: str
