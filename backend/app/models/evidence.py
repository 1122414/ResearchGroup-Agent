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


class EvidenceExcerpt(BaseModel):
    id: str
    run_id: str
    source_id: str
    excerpt: str
    locator: str = ""
    excerpt_type: str = "summary"
    captured_at: str


class EvidenceAssessment(BaseModel):
    id: str
    run_id: str
    source_id: str
    excerpt_id: str | None = None
    relevance_score: float = 0.0
    credibility_score: float = 0.0
    freshness_score: float = 0.0
    conflict_score: float = 0.0
    overall_score: float = 0.0
    is_primary: bool = False
    is_peer_reviewed: bool = False
    notes: str = ""
    created_at: str


class EvidenceLink(BaseModel):
    id: str
    run_id: str
    claim_id: str
    source_id: str
    excerpt_id: str | None = None
    relation_type: str = "supports"
    confidence: float = 0.0
    rationale: str = ""
    created_at: str
