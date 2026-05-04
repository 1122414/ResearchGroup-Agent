from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    idle = "idle"
    working = "working"
    waiting = "waiting"
    reviewing = "reviewing"
    blocked = "blocked"
    finished = "finished"


class SkillSet(BaseModel):
    literature_review: int = Field(default=1, ge=1, le=10)
    coding: int = Field(default=1, ge=1, le=10)
    experiment: int = Field(default=1, ge=1, le=10)
    data_analysis: int = Field(default=1, ge=1, le=10)
    academic_writing: int = Field(default=1, ge=1, le=10)
    mentoring: int = Field(default=1, ge=1, le=10)


class GraduateAgent(BaseModel):
    id: str
    name: str
    type: str
    description: str
    skills: SkillSet
    status: AgentStatus = AgentStatus.idle
    current_load: float = Field(default=0.0, ge=0.0, le=1.0)
    max_load: float = Field(default=1.0, ge=0.0, le=1.0)
    current_tasks: list[str] = Field(default_factory=list)
    preferred_task_types: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    can_create_subagents: bool = True
    max_subagents: int = Field(default=0, ge=0, le=3)
