import pytest

from backend.app.core.config import settings
from backend.app.services.grounding_audit_service import grounding_audit_service
from backend.app.services.research_integrity_service import research_integrity_service
from backend.app.services.review_service import review_service
from backend.app.services.source_verification_service import source_verification_service
from backend.app.services.task_executor import task_executor


def test_title_and_year_matching():
    svc = source_verification_service
    assert svc._title_matches("Retrieval Augmented Generation", "retrieval-augmented generation for NLP")
    assert not svc._title_matches("Retrieval Augmented Generation", "A study of protein folding")
    assert svc._year_matches(2023, 2023)
    assert svc._year_matches(2023, 2024)
    assert not svc._year_matches(2020, 2024)


def test_verdict_verified_and_mismatch():
    svc = source_verification_service
    source = {"title": "Deep Residual Learning for Image Recognition", "year": 2016}
    fetched = {"title": "Deep Residual Learning for Image Recognition", "year": 2016}
    verdict = svc._verdict(source, fetched)
    assert verdict["verified"] is True and verdict["status"] == "verified"

    bad = svc._verdict(source, {"title": "Completely Different Paper Title", "year": 1999})
    assert bad["verified"] is False and bad["status"] == "mismatch"


def test_doi_mismatch_is_not_citation_eligible(monkeypatch):
    monkeypatch.setattr(settings, "doi_verification_enabled", True)
    monkeypatch.setattr(
        source_verification_service,
        "_fetch_crossref",
        lambda _doi: {"title": "A different paper", "year": 1999},
    )
    source = {
        "title": "Claimed paper title",
        "year": 2024,
        "doi": "10.1000/example",
        "url": "https://doi.org/10.1000/example",
        "source_type": "paper",
        "metadata": {"provider": "crossref"},
    }
    verified = source_verification_service.verify_sources([source])[0]
    assert verified["metadata"]["verification_status"] == "doi_mismatch"
    assert verified["metadata"]["citation_eligible"] is False


def test_verified_doi_enriches_missing_authors_without_overwriting_claimed_metadata(monkeypatch):
    monkeypatch.setattr(settings, "doi_verification_enabled", True)
    monkeypatch.setattr(
        source_verification_service,
        "_fetch_crossref",
        lambda _doi: {
            "title": "Verified Paper", "year": 2024,
            "authors": "Jane Smith; Ann Lee", "venue": "Verified Journal",
        },
    )
    missing = {
        "title": "Verified Paper", "year": 2024, "authors": "", "venue": "",
        "doi": "10.1000/verified", "metadata": {},
    }
    claimed = {**missing, "authors": "Declared Author"}

    enriched, preserved = source_verification_service.verify_sources([missing, claimed])

    assert enriched["authors"] == "Jane Smith; Ann Lee"
    assert enriched["venue"] == "Verified Journal"
    assert enriched["metadata"]["bibliographic_enrichment_source"] == "crossref_doi_resolution"
    assert preserved["authors"] == "Declared Author"


def test_verify_sources_respects_flag(monkeypatch):
    monkeypatch.setattr(settings, "doi_verification_enabled", False)
    sources = [{"title": "x", "doi": None}]
    assert source_verification_service.verify_sources(sources) is sources

    monkeypatch.setattr(settings, "doi_verification_enabled", True)
    result = source_verification_service.verify_sources([{"title": "x", "doi": None}])
    assert result[0]["metadata"]["doi_verification"]["status"] == "no_doi"


def test_grounding_audit_detects_invalid_and_uncited(monkeypatch):
    monkeypatch.setattr(settings, "grounding_audit_enabled", True)
    report = "\n".join(
        [
            "# 研究论文：示例",
            "",
            "## 5. 结果",
            "",
            "- 方法在指标上显著优于基线方法 [1]",
            "- 这是一个没有任何引用支撑的事实性结论陈述句",
            "- 另一个结论引用了不存在的来源 [9]",
            "",
            "## 参考文献",
            "",
            "[1] Author (2020). A title. Venue",
            "",
        ]
    )
    audit = grounding_audit_service.audit_report(report)
    assert audit["checked"] is True
    assert audit["reference_count"] == 1
    assert 9 in audit["invalid_citations"]
    assert audit["uncited_claim_count"] >= 1
    assert audit["passed"] is False


def test_grounding_audit_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "grounding_audit_enabled", False)
    assert grounding_audit_service.audit_report("# x")["checked"] is False


def test_literature_policy_keeps_only_passage_grounded_claims(monkeypatch):
    monkeypatch.setattr(settings, "literature_min_grounded_sources", 1)
    source = {"id": "source_ok", "metadata": {"citation_eligible": True}}
    excerpt = {
        "id": "excerpt_ok", "source_id": "source_ok", "excerpt": "A real passage",
        "excerpt_type": "fulltext",
    }
    result = {
        "summary": "candidate conclusions",
        "references_used": ["source_ok"],
        "claims": [
            {
                "statement": "grounded", "evidence_source_ids": ["source_ok"],
                "evidence_passage_ids": ["excerpt_ok"], "relation": "supports", "confidence": 0.8,
            },
            {
                "statement": "not grounded", "evidence_source_ids": [],
                "evidence_passage_ids": [], "relation": "supports", "confidence": 0.8,
            },
        ],
    }
    checked = research_integrity_service.apply_literature_policy(
        result, [source], "query", "test", {"title": "brief"}, [excerpt]
    )
    assert [claim["statement"] for claim in checked["claims"]] == ["该研究在其设置下报告：grounded"]
    assert checked["academic_integrity"]["dropped_ungrounded_claims"] == 1


def test_literature_policy_accepts_structured_reference_screening_records(monkeypatch):
    monkeypatch.setattr(settings, "literature_min_grounded_sources", 1)
    source = {"id": "source_ok", "metadata": {"citation_eligible": True}}
    excerpt = {
        "id": "excerpt_ok", "source_id": "source_ok", "excerpt": "A real passage",
        "excerpt_type": "fulltext",
    }
    checked = research_integrity_service.apply_literature_policy(
        {
            "summary": "screened", "claims": [],
            "references_used": [{"source_id": "source_ok", "status": "accepted", "note": "relevant"}],
        },
        [source], "query", "test", {"title": "literature review"}, [excerpt],
    )

    assert checked["academic_integrity"]["status"] == "passed"
    assert checked["references_used"] == ["source_ok"]


def test_contextual_absence_is_kept_as_note_not_research_claim(monkeypatch):
    monkeypatch.setattr(settings, "literature_min_grounded_sources", 1)
    source = {"id": "source_ok", "metadata": {"citation_eligible": True}}
    excerpt = {
        "id": "excerpt_ok", "source_id": "source_ok", "excerpt": "The paper evaluates dense retrieval.",
        "excerpt_type": "fulltext",
    }
    result = {
        "summary": "search gap",
        "claims": [{
            "statement": "The source does not compare chunk overlap settings.",
            "evidence_source_ids": ["source_ok"], "evidence_passage_ids": ["excerpt_ok"],
            "relation": "context", "confidence": 0.8,
        }],
    }

    checked = research_integrity_service.apply_literature_policy(
        result, [source], "chunking literature", "test", {"title": "literature review"}, [excerpt],
    )

    assert checked["claims"] == []
    assert len(checked["context_notes"]) == 1
    assert checked["academic_integrity"]["context_claims_moved_to_notes"] == 1


def test_literature_policy_allows_locator_of_whitelisted_url(monkeypatch):
    monkeypatch.setattr(settings, "literature_min_grounded_sources", 1)
    sources = [{
        "id": "source_ok", "url": "https://arxiv.org/abs/2603.06976v1",
        "metadata": {"citation_eligible": True},
    }]
    excerpts = [{
        "id": "excerpt_ok", "source_id": "source_ok", "excerpt": "A real passage",
        "locator": "http://arxiv.org/abs/2603.06976v1#chars=0-4000",
        "excerpt_type": "fulltext",
    }]
    result = {
        "summary": "See http://arxiv.org/abs/2603.06976v1#chars=0-4000",
        "references_used": ["source_ok"],
        "claims": [{
            "statement": "该论文报告了一个受限结果。",
            "evidence_source_ids": ["source_ok"], "evidence_passage_ids": ["excerpt_ok"],
            "relation": "supports", "confidence": 0.8,
        }],
    }
    checked = research_integrity_service.apply_literature_policy(
        result, sources, "query", "test", {"title": "论文综述"}, excerpts
    )
    assert checked["academic_integrity"]["status"] == "passed"
    assert len(checked["claims"]) == 1


def test_literature_policy_allows_verified_source_passage_bracket(monkeypatch):
    monkeypatch.setattr(settings, "literature_min_grounded_sources", 1)
    source = {"id": "source_ok", "metadata": {"citation_eligible": True}}
    excerpt = {
        "id": "excerpt_ok", "source_id": "source_ok", "excerpt": "A real passage",
        "excerpt_type": "fulltext",
    }
    result = {
        "summary": "受限结论 [source_ok/excerpt_ok]",
        "references_used": ["source_ok"],
        "claims": [{
            "statement": "该研究报告受限结论", "evidence_source_ids": ["source_ok"],
            "evidence_passage_ids": ["excerpt_ok"], "relation": "supports", "confidence": 0.8,
        }],
    }
    checked = research_integrity_service.apply_literature_policy(
        result, [source], "query", "test", {"title": "论文综述"}, [excerpt]
    )
    assert checked["academic_integrity"]["status"] == "passed"


def test_literature_policy_blocks_mismatched_source_passage_bracket(monkeypatch):
    monkeypatch.setattr(settings, "literature_min_grounded_sources", 1)
    sources = [{"id": "source_a"}, {"id": "source_b"}]
    excerpt = {"id": "excerpt_b", "source_id": "source_b", "excerpt": "passage"}
    checked = research_integrity_service.apply_literature_policy(
        {"summary": "错误配对 [source_a/excerpt_b]", "references_used": ["source_a"]},
        sources, "query", "test", {"title": "论文综述"}, [excerpt],
    )
    assert checked["academic_integrity"]["status"] == "blocked_fabrication"


def test_literature_policy_still_blocks_different_url(monkeypatch):
    monkeypatch.setattr(settings, "literature_min_grounded_sources", 1)
    source = {"id": "source_ok", "url": "https://arxiv.org/abs/2603.06976v1"}
    excerpt = {"id": "excerpt_ok", "source_id": "source_ok", "excerpt": "passage"}
    checked = research_integrity_service.apply_literature_policy(
        {"summary": "See https://arxiv.org/abs/9999.99999", "references_used": ["source_ok"]},
        [source], "query", "test", {"title": "论文综述"}, [excerpt],
    )
    assert checked["academic_integrity"]["status"] == "blocked_fabrication"


def test_review_invalid_structure_fails_closed():
    assert review_service._parse_review("not json")["review_transport_failed"] is True
    assert review_service._parse_review('{"feedback":"missing decision"}')["approved"] is False


def test_advisor_payload_omits_raw_passages_but_keeps_traceability():
    payload = review_service._advisor_payload({
        "summary": "synthesis",
        "claims": [{"statement": "supported"}],
        "evidence_excerpts": [{"excerpt": "x" * 50000}],
        "evidence_assessments": [{"overall_score": 1}],
        "papers_read": [{
            "id": "source_1", "title": "Paper", "url": "https://example.test/paper",
            "metadata": {"content": "x" * 50000},
        }],
    })

    assert "evidence_excerpts" not in payload
    assert "evidence_assessments" not in payload
    assert payload["papers_read"] == [{
        "id": "source_1", "title": "Paper", "url": "https://example.test/paper",
    }]


def test_result_analysis_rubric_accepts_verified_experiment_metrics(monkeypatch):
    monkeypatch.setattr(settings, "review_default_approved_score", 0.8)
    rubric = review_service._rubric_for_task("result_analysis")
    scores = review_service._score_task(
        {
            "task_type": "result_analysis",
            "outputs": [{
                "reproducible_experiment": {
                    "metrics": {"rows": [{"strategy": "overlap", "mrr": 1.0}]},
                    "reproduction": {"passed": True},
                },
            }],
        },
        {"approved": True},
        rubric,
    )

    assert scores["evidence"] == 1.0
    assert sum(scores.values()) / len(scores) >= rubric["threshold"]


@pytest.mark.asyncio
async def test_structured_output_repair_is_bounded(monkeypatch):
    class InvalidLLM:
        calls = 0

        async def generate(self, **_kwargs):
            self.calls += 1
            return "not json"

    llm = InvalidLLM()
    monkeypatch.setattr(settings, "llm_structured_repair_attempts", 1)
    with pytest.raises(ValueError, match="after 2 attempt"):
        await task_executor._generate_structured(llm, "prompt", {"id": "task", "run_id": None}, "agent")
    assert llm.calls == 2
