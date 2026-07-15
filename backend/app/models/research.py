from typing import Any, Literal

from pydantic import BaseModel, Field


class ResearchBrief(BaseModel):
    id: str
    run_id: str
    research_question: str
    objective: str
    scope: str = ""
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    research_type: Literal["empirical", "survey", "design", "mixed", "interpretive", "theoretical"] = "empirical"
    subquestions: list[dict] = Field(default_factory=list)
    scope_in: list[str] = Field(default_factory=list)
    scope_out: list[str] = Field(default_factory=list)
    target_domain: str = ""
    expected_contribution: str = ""
    novelty_criteria: list[str] = Field(default_factory=list)
    data_availability: str = ""
    ethics_risks: list[str] = Field(default_factory=list)
    failure_criteria: list[str] = Field(default_factory=list)
    discipline: dict = Field(default_factory=dict)
    methodology_family: str = ""
    epistemic_mode: str = ""
    methodology_profile: dict = Field(default_factory=dict)
    resource_plan: list[dict] = Field(default_factory=list)
    ethics_plan: dict = Field(default_factory=dict)
    thesis_requirements: dict = Field(default_factory=dict)
    feasibility_assessment: dict = Field(default_factory=dict)
    approval_status: Literal["draft", "frozen", "needs_revision", "blocked_resources", "rejected"] = "draft"
    validation_errors: list[str] = Field(default_factory=list)
    status: Literal["draft", "active", "frozen", "revised"] = "draft"
    created_at: str
    updated_at: str


class Hypothesis(BaseModel):
    id: str
    run_id: str
    statement: str
    rationale: str = ""
    status: Literal["proposed", "active", "supported", "rejected", "revised"] = "proposed"
    confidence: float = 0.0
    treatment: str = ""
    baseline: str = ""
    conditions: list[str] = Field(default_factory=list)
    predicted_direction: str = ""
    primary_metric: str = ""
    minimum_effect: str = ""
    falsification_criterion: str = ""
    originating_evidence_ids: list[str] = Field(default_factory=list)
    competing_hypothesis_ids: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class ResearchMilestone(BaseModel):
    id: str
    run_id: str
    milestone_key: str
    title: str
    status: Literal["pending", "passed", "blocked", "waived"] = "pending"
    criteria: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    completed_at: str | None = None
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


class ResearchActionContract(BaseModel):
    id: str
    round: int = Field(ge=1)
    objective: str
    target: dict[str, Any]
    selected_tool: Literal["evidence_search", "experiment_runner", "result_analyzer"]
    arguments: dict[str, Any] = Field(default_factory=dict)
    expected_observation: str
    success_condition: str
    failure_handling: str
    budget: dict[str, float | int]
    safety_level: Literal["low", "medium", "high"] = "low"
    provenance: dict[str, Any]
    fingerprint: str
    expected_information_gain: float = Field(ge=0, le=1)
    critic: dict[str, Any] = Field(default_factory=dict)
