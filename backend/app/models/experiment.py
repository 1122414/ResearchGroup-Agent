from typing import Literal

from pydantic import BaseModel, Field


ExperimentStatus = Literal["draft", "needs_review", "approved", "rejected", "running", "completed", "failed"]
ExperimentRiskLevel = Literal["safe", "needs_review", "dangerous"]
ProtocolStatus = Literal["draft", "ready", "running", "completed", "failed"]
FindingRelationType = Literal["supports", "weakens", "rejects", "inconclusive"]


class ExperimentFile(BaseModel):
    path: str
    content: str


class ExperimentCommand(BaseModel):
    command: str
    description: str = ""


class ExperimentResult(BaseModel):
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    elapsed_ms: int = 0
    command_results: list[dict] = Field(default_factory=list)


class DatasetSpec(BaseModel):
    name: str
    source: str
    path: str | None = None
    description: str = ""
    snapshot_hash: str | None = None


class MetricSpec(BaseModel):
    name: str
    description: str = ""
    direction: Literal["maximize", "minimize"] = "maximize"


class BaselineSpec(BaseModel):
    name: str
    description: str = ""


class ExperimentProtocol(BaseModel):
    id: str
    run_id: str
    hypothesis_id: str
    task_id: str | None = None
    title: str
    research_question: str
    independent_variables: list[str] = Field(default_factory=list)
    dependent_variables: list[str] = Field(default_factory=list)
    datasets: list[DatasetSpec] = Field(default_factory=list)
    metrics: list[MetricSpec] = Field(default_factory=list)
    baselines: list[BaselineSpec] = Field(default_factory=list)
    stopping_conditions: list[str] = Field(default_factory=list)
    expected_risks: list[str] = Field(default_factory=list)
    status: ProtocolStatus = "draft"
    created_at: str
    updated_at: str


class ExperimentRun(BaseModel):
    id: str
    protocol_id: str
    plan_id: str | None = None
    run_id: str
    task_id: str | None = None
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    command: str = ""
    dataset_snapshot: dict = Field(default_factory=dict)
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str


class ExperimentFinding(BaseModel):
    id: str
    protocol_id: str
    experiment_run_id: str
    result_id: str
    run_id: str
    hypothesis_id: str
    claim_id: str | None = None
    relation_type: FindingRelationType
    statement: str
    confidence: float = 0.0
    created_at: str


class ExperimentPlan(BaseModel):
    id: str
    run_id: str | None = None
    task_id: str | None = None
    agent_id: str = "experiment_agent"
    title: str
    objective: str = ""
    workspace_dir: str = ""
    files: list[ExperimentFile] = Field(default_factory=list)
    commands: list[ExperimentCommand] = Field(default_factory=list)
    env_vars: dict[str, str] = Field(default_factory=dict)
    risk_level: ExperimentRiskLevel = "needs_review"
    risk_reasons: list[str] = Field(default_factory=list)
    status: ExperimentStatus = "draft"
    result: ExperimentResult | None = None
    artifacts: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    approved_at: str | None = None
    approved_by: str | None = None


class ExperimentPlanCreate(BaseModel):
    run_id: str | None = None
    task_id: str | None = None
    agent_id: str = "experiment_agent"
    title: str
    objective: str = ""
    workspace_dir: str | None = None
    files: list[ExperimentFile] = Field(default_factory=list)
    commands: list[ExperimentCommand] = Field(default_factory=list)
    env_vars: dict[str, str] = Field(default_factory=dict)


class ExperimentPlanUpdate(BaseModel):
    title: str | None = None
    objective: str | None = None
    workspace_dir: str | None = None
    files: list[ExperimentFile] | None = None
    commands: list[ExperimentCommand] | None = None
    env_vars: dict[str, str] | None = None


class ExperimentApproval(BaseModel):
    approved_by: str = "user"


class ExperimentReject(BaseModel):
    reason: str = ""
