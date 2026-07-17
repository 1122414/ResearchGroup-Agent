import uuid

import pytest

from backend.app.core.config import settings
from backend.app.services.claim_entailment_service import claim_entailment_service
from backend.app.services.evidence_pipeline_service import evidence_pipeline_service
from backend.app.services.fulltext_ingest_service import fulltext_ingest_service
from backend.app.services.source_verification_service import source_verification_service
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


def test_fulltext_limit_cannot_make_literature_contract_impossible(monkeypatch):
    run_id = f"run_fulltext_limit_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "fulltext_ingest_enabled", True)
    monkeypatch.setattr(settings, "fulltext_max_sources", 1)
    monkeypatch.setattr(settings, "literature_source_limit", 3)
    monkeypatch.setattr(fulltext_ingest_service, "_fetch_text", lambda _url: ("grounded passage", "html"))

    count = fulltext_ingest_service.ingest_sources(
        run_id,
        [
            {"id": f"source_{index}", "url": f"https://example.test/paper-{index}"}
            for index in range(4)
        ],
    )

    assert count == 3


def test_fulltext_readability_filter_rejects_redirect_and_accepts_article_text():
    assert fulltext_ingest_service._usable_text("Redirecting") == ""
    readable = "This verified article reports a reproducible method and result. " * 8
    assert fulltext_ingest_service._usable_text(readable) == readable.strip()


def test_fulltext_fetch_rejects_office_archive_mislabeled_as_html(monkeypatch):
    class Response:
        headers = {"Content-Type": "text/html"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read(_limit):
            return b"PK\x03\x04" + b"\x00" * 1000

    monkeypatch.setattr(
        "backend.app.services.fulltext_ingest_service.urllib.request.urlopen",
        lambda *_args, **_kwargs: Response(),
    )

    assert fulltext_ingest_service._fetch_text("https://example.test/chart") == (
        "", "unsupported_binary",
    )


def test_source_ids_and_fulltext_ingestion_are_stable_within_run(monkeypatch):
    run_id = f"run_fulltext_stable_{uuid.uuid4().hex[:8]}"
    raw = {"id": "arxiv:1234.56789", "title": "Stable Paper", "url": "https://arxiv.org/abs/1234.56789"}
    first = evidence_pipeline_service._normalize_source(raw, {"id": "task_a", "run_id": run_id})
    second = evidence_pipeline_service._normalize_source(raw, {"id": "task_revision", "run_id": run_id})
    assert first["id"] == second["id"]

    calls = []
    monkeypatch.setattr(settings, "fulltext_ingest_enabled", True)
    monkeypatch.setattr(settings, "literature_source_limit", 1)
    monkeypatch.setattr(fulltext_ingest_service, "_fetch_text", lambda url: (calls.append(url) or "paper text", "html"))
    assert fulltext_ingest_service.ingest_sources(run_id, [first]) == 1
    initial = EvidenceRepository.get_by_run(run_id)
    assert fulltext_ingest_service.ingest_sources(run_id, [second]) == 1
    repeated = EvidenceRepository.get_by_run(run_id)

    assert calls == [raw["url"]]
    assert len(repeated["excerpts"]) == len(initial["excerpts"])


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


def test_seed_sources_are_reintroduced_into_each_run_search():
    run_id = f"run_seed_{uuid.uuid4().hex[:8]}"
    EvidenceRepository.upsert_source({
        "id": "seed_source_one", "run_id": run_id, "task_id": None,
        "title": "Verified Seed", "url": "https://example.test/seed",
        "metadata": {"origin": "user_seed"}, "created_at": "2026-07-15T00:00:00",
    })
    EvidenceRepository.upsert_source({
        "id": "ordinary_source", "run_id": run_id, "task_id": None,
        "title": "Ordinary", "url": "https://example.test/ordinary",
        "metadata": {}, "created_at": "2026-07-15T00:00:00",
    })

    result = evidence_pipeline_service._seed_sources(run_id)

    assert [item["id"] for item in result] == ["seed_source_one"]


def test_seed_sources_are_kept_ahead_of_result_truncation():
    ranked = [
        {"id": "search_1", "metadata": {"provider": "crossref"}},
        {"id": "seed_1", "metadata": {"origin": "user_seed"}},
        {"id": "search_2", "metadata": {"provider": "arxiv"}},
        {"id": "seed_2", "metadata": {"origin": "user_seed"}},
    ]

    result = evidence_pipeline_service._prioritize_seed_sources(ranked)

    assert [item["id"] for item in result] == ["seed_1", "seed_2", "search_1", "search_2"]


def test_user_seed_is_fetched_before_title_relevance_can_exclude_it():
    sources = [
        {
            "id": "seed_report", "title": "Education Finance Watch 2024",
            "metadata": {"origin": "user_seed"},
        },
        {
            "id": "search_noise", "title": "National health expenditure and GDP",
            "metadata": {"provider": "crossref"},
        },
        {
            "id": "search_match", "title": "Government education expenditure by income group",
            "metadata": {"provider": "crossref"},
        },
    ]

    ranked = evidence_pipeline_service._rank_by_relevance(
        sources,
        "government education expenditure GDP high income lower middle income",
        preserve_user_sources=True,
    )

    assert [source["id"] for source in ranked] == ["seed_report", "search_match"]


def test_fetched_seed_fulltext_verifies_identity_and_becomes_citation_eligible(monkeypatch):
    run_id = f"run_seed_fulltext_{uuid.uuid4().hex[:8]}"
    source = {
        "id": "seed_report", "title": "Education Finance Watch 2024",
        "url": "https://example.test/report.pdf", "source_type": "report",
        "metadata": {"origin": "user_seed"},
    }
    text = (
        "Education Finance Watch 2024. World Bank and UNESCO. "
        "Government education expenditure as a percentage of GDP by income group. "
    ) * 8
    monkeypatch.setattr(settings, "fulltext_ingest_enabled", True)
    monkeypatch.setattr(settings, "doi_verification_enabled", False)
    monkeypatch.setattr(fulltext_ingest_service, "_fetch_text", lambda _url: (text, "pdf"))

    assert fulltext_ingest_service.ingest_sources(run_id, [source]) == 1
    verified = source_verification_service.verify_sources([source])[0]

    proof = verified["metadata"]["fulltext_identity_verification"]
    assert proof["verified"] is True
    assert len(proof["content_hash"]) == 64
    assert verified["metadata"]["verification_status"] == "user_seed_fulltext_identity_verified"
    assert verified["metadata"]["citation_eligible"] is True


def test_grounded_generic_seed_requires_topic_overlap_in_downloaded_passage():
    sources = [
        {
            "id": "relevant_seed", "title": "Education Finance Watch 2024",
            "metadata": {
                "origin": "user_seed",
                "fulltext_identity_verification": {"verified": True, "content_hash": "a" * 64},
            },
        },
        {
            "id": "irrelevant_seed", "title": "Annual Review 2024",
            "metadata": {
                "origin": "user_seed",
                "fulltext_identity_verification": {"verified": True, "content_hash": "b" * 64},
            },
        },
    ]
    excerpts = [
        {
            "id": "p1", "source_id": "relevant_seed",
            "excerpt": "Government education expenditure as a percentage of GDP by income group.",
        },
        {
            "id": "p2", "source_id": "irrelevant_seed",
            "excerpt": "Particle collision detector calibration and luminosity.",
        },
    ]

    ranked, selected = evidence_pipeline_service._rank_grounded_bundle(
        sources,
        excerpts,
        "government education expenditure GDP high income lower middle income",
    )

    assert [source["id"] for source in ranked] == ["relevant_seed"]
    assert [excerpt["id"] for excerpt in selected] == ["p1"]
