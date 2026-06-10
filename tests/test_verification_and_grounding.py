from backend.app.core.config import settings
from backend.app.services.grounding_audit_service import grounding_audit_service
from backend.app.services.source_verification_service import source_verification_service


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
