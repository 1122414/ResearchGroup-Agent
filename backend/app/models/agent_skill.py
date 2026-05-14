from typing import Literal

from pydantic import BaseModel, Field


SkillStatus = Literal["draft", "active", "disabled", "archived"]


class AgentSkill(BaseModel):
    id: str
    agent_id: str
    title: str
    description: str = ""
    content: str
    status: SkillStatus = "draft"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_run_id: str | None = None
    source_task_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    file_path: str = ""
    usage_count: int = 0
    failure_count: int = 0
    created_at: str
    updated_at: str
    last_used_at: str | None = None


class AgentSkillCreate(BaseModel):
    agent_id: str
    title: str
    description: str = ""
    content: str
    status: SkillStatus = "active"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_run_id: str | None = None
    source_task_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class AgentSkillUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    content: str | None = None
    status: SkillStatus | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    tags: list[str] | None = None
