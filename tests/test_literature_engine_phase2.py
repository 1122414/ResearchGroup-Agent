import uuid

import pytest

from backend.app.core.config import settings
from backend.app.services.claim_entailment_service import claim_entailment_service
from backend.app.services.evidence_pipeline_service import evidence_pipeline_service
from backend.app.services.fulltext_ingest_service import fulltext_ingest_service
from backend.app.storage import init_db
from backend.app.storage.repositories import (
    EvidenceRepository,
    FullTextDocumentRepository,
    LiteratureSearchRepository,
)


@pytest.fixture(autouse=True)
def _db():
    init_db()


@pytest.mark.asyncio
async def test_entailment_gate_rejects_claim_without_real_passage(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    result = {
        "summary": "candidate",
        "claims": [
            {"statement": "kept", "evidence_passage_ids": ["passage_ok"], "confidence": 0.8},
            {"statement": "rejected", "evidence_passage_ids": ["passage_missing"], "confidence": 0.8},
        ],
    }
    checked = await claim_entailment_service.verify(
        result,
        [{"id": "passage_ok", "source_id": "source_ok", "excerpt": "supporting text"}],
        None,
        None,
    )
    assert [item["statement"] for item in checked["claims"]] == ["kept"]
    assert checked["claims"][0]["entailment_verdict"] == "entailed"
    assert checked["entailment_audit"]["rejected"] == 1


def test_fulltext_is_hashed_and_split_into_locatable_passages(monkeypatch):
    run_id = f"run_fulltext_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "fulltext_ingest_enabled", True)
    monkeypatch.setattr(settings, "evidence_excerpt_max_chars", 20)
    monkeypatch.setattr(fulltext_ingest_service, "_fetch_text", lambda _url: ("A" * 45, "html"))

    count = fulltext_ingest_service.ingest_sources(
        run_id,
        [{"id": "source_fulltext", "url": "https://example.test/paper"}],
    )
    evidence = EvidenceRepository.get_by_run(run_id)
    documents = FullTextDocumentRepository.get_by_run(run_id)

    assert count == 1
    assert len(documents) == 1 and len(documents[0]["content_hash"]) == 64
    assert len(evidence["excerpts"]) == 3
    assert all("#chars=" in item["locator"] for item in evidence["excerpts"])
    assert all(item["document_id"] == documents[0]["id"] for item in evidence["excerpts"])


def test_search_protocol_and_runs_are_replayable_snapshots():
    run_id = f"run_search_{uuid.uuid4().hex[:8]}"
    task = {"id": "task_search", "run_id": run_id}
    attempts = [{"provider": "crossref", "query": "rag evaluation", "result_count": 3, "error": None}]
    protocol_id = evidence_pipeline_service._record_search_protocol(task, ["rag evaluation"], attempts)
    evidence_pipeline_service._record_search_runs(task, protocol_id, attempts)

    audit = LiteratureSearchRepository.get_by_run(run_id)
    assert audit["protocols"][0]["queries"] == ["rag evaluation"]
    assert audit["runs"][0]["provider"] == "crossref"
    assert len(audit["runs"][0]["response_hash"]) == 64


def test_deduplication_uses_normalized_title_and_author_when_ids_missing():
    sources = [
        {"title": "A Study: of RAG", "authors": "A. Author", "metadata": {}},
        {"title": "A Study of RAG", "authors": "A Author", "metadata": {}},
    ]
    assert len(evidence_pipeline_service._deduplicate_sources(sources)) == 1
