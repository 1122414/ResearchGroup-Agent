import uuid
from datetime import datetime

import pytest

from backend.app.services.knowledge_graph_service import knowledge_graph_service
from backend.app.storage.repositories import (
    EvidenceRepository,
    ResearchClaimRepository,
    ResearchHypothesisRepository,
    ResearchUncertaintyRepository,
)
from backend.app.storage import init_db


@pytest.fixture(autouse=True)
def _db():
    init_db()


def _seed_source(run_id: str, source_id: str) -> str:
    now = datetime.now().isoformat()
    EvidenceRepository.upsert_source(
        {
            "id": source_id,
            "run_id": run_id,
            "task_id": None,
            "title": "A grounded source",
            "authors": "Author",
            "year": 2024,
            "venue": "Venue",
            "doi": None,
            "url": "https://example.com/x",
            "source_type": "paper",
            "metadata": {"citation_eligible": True},
            "created_at": now,
        }
    )
    excerpt_id = f"excerpt_{uuid.uuid4().hex[:8]}"
    EvidenceRepository.insert_excerpt(
        {
            "id": excerpt_id,
            "run_id": run_id,
            "source_id": source_id,
            "excerpt": "relevant passage",
            "locator": "https://example.com/x",
            "excerpt_type": "fulltext",
            "captured_at": now,
        }
    )
    return excerpt_id


def test_ingest_creates_claims_links_and_filters_fabricated_sources():
    run_id = f"run_kg_{uuid.uuid4().hex[:6]}"
    good_source = f"source_{uuid.uuid4().hex[:8]}"
    passage_id = _seed_source(run_id, good_source)

    task = {"id": f"task_{uuid.uuid4().hex[:6]}", "run_id": run_id, "task_type": "literature_survey"}
    result = {
        "summary": "s",
        "claims": [
            {
                "statement": "Grounded claim backed by a real source.",
                "evidence_source_ids": [good_source, "source_fabricated_999"],
                "evidence_passage_ids": [passage_id],
                "relation": "supports",
                "confidence": 0.8,
            },
            {
                "statement": "Ungrounded claim with no evidence.",
                "evidence_source_ids": [],
                "evidence_passage_ids": [],
                "relation": "supports",
            },
        ],
        "hypotheses": [{"statement": "H1 is testable.", "rationale": "because"}],
        "uncertainties": [{"description": "Open question remains.", "severity": "high"}],
    }

    graph = knowledge_graph_service.ingest_task_result(task, result)

    assert len(graph["claims"]) == 2
    # Only the real source is linked; the fabricated id is dropped.
    assert graph["evidence_links"] == 1
    assert len(graph["hypotheses"]) == 1
    assert len(graph["uncertainties"]) == 1

    claims = ResearchClaimRepository.get_by_run(run_id)
    grounded = next(c for c in claims if "Grounded" in c["statement"])
    # Linked claim resolves its evidence source id from the link evaluation.
    assert good_source in grounded["evidence_ids"]

    hypotheses = ResearchHypothesisRepository.get_by_run(run_id)
    assert any("H1" in h["statement"] for h in hypotheses)
    uncertainties = ResearchUncertaintyRepository.get_by_run(run_id)
    assert any(u["severity"] == "high" for u in uncertainties)
