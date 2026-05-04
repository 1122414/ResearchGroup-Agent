from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class SubAgentLifecycle(str, Enum):
    destroy_after_return = "destroy_after_return"
    destroyed = "destroyed"


class SubAgentCreate(BaseModel):
    parent_agent: str
    task_id: str
    task: str
    context: str = ""
    expected_output_schema: dict = Field(default_factory=dict)


class SubAgent(BaseModel):
    id: str
    parent_agent: str
    task_id: str
    task: str
    context: str = ""
    expected_output_schema: dict = Field(default_factory=dict)
    status: str = "running"
    lifecycle: SubAgentLifecycle = SubAgentLifecycle.destroy_after_return
    result: Optional[dict] = None
