import pytest

from backend.app.core.config import settings
from backend.app.services.scientific_quality_gate_service import scientific_quality_gate_service
from backend.app.services.independent_reviewer_service import independent_reviewer_service
from backend.app.storage.repositories import (
    EvidenceRepository,
    ExperimentResultRepository,
    ResearchBriefRepository,
    ResearchClaimRepository,
    TaskRepository,
)


def _evidence():
    return {
        "sources": [{"id": "source_1", "metadata": {"citation_eligible": True}}],
        "excerpts": [{
            "id": "passage_1", "source_id": "source_1", "excerpt": "The method improves retrieval accuracy.",
            "excerpt_type": "fulltext", "locator": "p.1",
        }],
        "claims": [], "assessments": [], "links": [],
    }


@pytest.mark.asyncio
async def test_five_layer_task_gate_accepts_grounded_claim(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(EvidenceRepository, "get_by_run", lambda _run_id: _evidence())
    task = {"id": "task_1", "run_id": "run_1", "task_type": "literature_survey"}
    latest = {
        "summary": "grounded", "entailment_audit": {"checked": True, "kept": 1, "rejected": 0},
        "claims": [{
            "statement": "The method improves retrieval accuracy.",
            "evidence_source_ids": ["source_1"], "evidence_passage_ids": ["passage_1"],
            "entailment_verdict": "entailed",
        }],
    }
    quality = await scientific_quality_gate_service.evaluate_task(task, latest)
    assert quality["passed"] is True
    assert set(quality["layers"]) == {"schema", "provenance", "semantic", "method", "independent_review"}


@pytest.mark.asyncio
async def test_high_risk_claim_requires_two_sources(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(EvidenceRepository, "get_by_run", lambda _run_id: _evidence())
    task = {"id": "task_1", "run_id": "run_1", "task_type": "literature_survey"}
    latest = {
        "summary": "overclaim", "entailment_audit": {"checked": True},
        "claims": [{
            "statement": "This proves the method causes significant improvement.",
            "evidence_source_ids": ["source_1"], "evidence_passage_ids": ["passage_1"],
            "entailment_verdict": "entailed",
        }],
    }
    quality = await scientific_quality_gate_service.evaluate_task(task, latest)
    assert quality["passed"] is False
    assert "claim_0:high_risk_requires_two_sources" in quality["layers"]["semantic"]["issues"]
    assert quality["layers"]["independent_review"]["reviewer"] == "not_called_after_hard_gate_failure"


def test_report_gate_rejects_task_without_independent_quality_record(monkeypatch):
    monkeypatch.setattr(EvidenceRepository, "get_by_run", lambda _run_id: _evidence())
    monkeypatch.setattr(ResearchClaimRepository, "get_by_run", lambda _run_id: [])
    monkeypatch.setattr(ResearchBriefRepository, "get_by_run", lambda _run_id: {"research_type": "survey"})
    monkeypatch.setattr(ExperimentResultRepository, "get_by_run", lambda _run_id: [])
    monkeypatch.setattr(
        TaskRepository, "get_all",
        lambda run_id=None: [{
            "id": "task_old", "task_type": "literature_survey", "status": "completed", "review_result": {},
        }],
    )
    quality = scientific_quality_gate_service.evaluate_report(
        "run_1", "# Report\n\n## 参考文献\n", {"passed": True},
    )
    assert quality["passed"] is False
    assert quality["layers"]["independent_review"]["issues"] == ["task_without_full_quality_gate:task_old"]


@pytest.mark.asyncio
async def test_independent_reviewer_failure_is_fail_closed(monkeypatch):
    class BrokenReviewer:
        async def generate(self, **_kwargs):
            raise RuntimeError("reviewer unavailable")

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.create_llm_provider",
        lambda: BrokenReviewer(),
    )
    result = await independent_reviewer_service.review_task(
        {"id": "task_1", "run_id": "run_1", "task_type": "literature_survey"},
        {"claims": []},
        {"excerpts": []},
    )
    assert result["approved"] is False
    assert result["reviewer"] == "independent_reviewer_schema_guard"
