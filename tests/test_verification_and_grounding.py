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
    assert [claim["statement"] for claim in checked["claims"]] == ["grounded"]
    assert checked["academic_integrity"]["dropped_ungrounded_claims"] == 1


def test_review_invalid_structure_fails_closed():
    assert review_service._parse_review("not json")["approved"] is False
    assert review_service._parse_review('{"feedback":"missing decision"}')["approved"] is False


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
