from pydantic import BaseModel, Field


class EvidenceSource(BaseModel):
    id: str
    run_id: str
    task_id: str | None = None
    title: str
    authors: str = ""
    year: int | None = None
    venue: str = ""
    doi: str | None = None
    url: str | None = None
    source_type: str = "paper"
    metadata: dict = Field(default_factory=dict)
    created_at: str


class EvidenceClaim(BaseModel):
    id: str
    run_id: str
    task_id: str | None = None
    source_id: str
    claim: str
    method: str = ""
    relation_type: str = "supports"
    created_at: str
