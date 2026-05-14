from typing import Literal

from pydantic import BaseModel, Field


ExperimentStatus = Literal["draft", "needs_review", "approved", "rejected", "running", "completed", "failed"]
ExperimentRiskLevel = Literal["safe", "needs_review", "dangerous"]


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

