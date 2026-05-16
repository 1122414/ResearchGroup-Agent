from pydantic import BaseModel, Field


class ReviewRubric(BaseModel):
    dimensions: dict[str, float] = Field(default_factory=dict)
    threshold: float = 0.75


class ReviewDecision(BaseModel):
    id: str
    run_id: str
    task_id: str
    rubric: dict = Field(default_factory=dict)
    scores: dict[str, float] = Field(default_factory=dict)
    approved: bool = True
    feedback: str = ""
    requires_revision: bool = False
    created_at: str
