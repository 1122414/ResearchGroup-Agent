from typing import Literal

from pydantic import BaseModel, Field


class ResearchBrief(BaseModel):
    id: str
    run_id: str
    research_question: str
    objective: str
    scope: str = ""
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    status: Literal["draft", "active", "revised"] = "active"
    created_at: str
    updated_at: str


class Hypothesis(BaseModel):
    id: str
    run_id: str
    statement: str
    rationale: str = ""
    status: Literal["proposed", "active", "supported", "rejected", "revised"] = "proposed"
    confidence: float = 0.0
    created_at: str
    updated_at: str


class Claim(BaseModel):
    id: str
    run_id: str
    hypothesis_id: str | None = None
    statement: str
    status: Literal["draft", "supported", "contested", "retracted"] = "draft"
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    created_at: str
    updated_at: str


class DecisionLog(BaseModel):
    id: str
    run_id: str
    decision: str
    rationale: str = ""
    impact: str = ""
    created_at: str


class Uncertainty(BaseModel):
    id: str
    run_id: str
    description: str
    category: str = "research_question"
    severity: Literal["low", "medium", "high"] = "medium"
    status: Literal["open", "resolved"] = "open"
    created_at: str
    resolved_at: str | None = None
