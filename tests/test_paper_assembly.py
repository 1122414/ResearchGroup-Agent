import uuid
from datetime import datetime

import pytest

from backend.app.services.paper_assembly_service import paper_assembly_service
from backend.app.services.grounding_audit_service import grounding_audit_service
from backend.app.services.report_service import ReportService
from backend.app.storage import init_db
from backend.app.storage.repositories import (
    EvidenceRepository,
    ExperimentResultRepository,
    ResearchClaimRepository,
    RunRepository,
)


@pytest.fixture(autouse=True)
def _db():
    init_db()


def _make_run(goal: str) -> dict:
    now = datetime.now().isoformat()
    run = {
        "id": f"run_pa_{uuid.uuid4().hex[:6]}",
        "research_goal": goal,
        "status": "completed",
        "created_at": now,
        "updated_at": now,
    }
    RunRepository.insert(run)
    return run


def test_paper_mode_is_grounded_with_inline_citations_and_references():
    run = _make_run("compare retrieval strategies for RAG")
    now = datetime.now().isoformat()
    source_id = f"source_{uuid.uuid4().hex[:8]}"
    EvidenceRepository.upsert_source(
        {
            "id": source_id, "run_id": run["id"], "task_id": None,
            "title": "Dense Passage Retrieval", "authors": "Karpukhin et al.", "year": 2020,
            "venue": "EMNLP", "doi": None, "url": "https://arxiv.org/abs/2004.04906",
            "source_type": "paper", "metadata": {"citation_eligible": True}, "created_at": now,
        }
    )
    excerpt_id = f"excerpt_{uuid.uuid4().hex[:8]}"
    EvidenceRepository.insert_excerpt(
        {
            "id": excerpt_id, "run_id": run["id"], "source_id": source_id,
            "excerpt": "Dense retrieval reports higher recall than BM25 on the evaluated benchmark.",
            "locator": "https://arxiv.org/abs/2004.04906", "excerpt_type": "fulltext",
            "captured_at": now,
        }
    )
    claim_id = f"claim_{uuid.uuid4().hex[:8]}"
    ResearchClaimRepository.insert(
        {
            "id": claim_id, "run_id": run["id"], "hypothesis_id": None,
            "statement": "Dense retrieval improves recall over BM25.",
            "status": "supported", "evidence_ids": [source_id], "confidence": 0.8,
            "created_at": now, "updated_at": now,
        }
    )
    EvidenceRepository.insert_link(
        {
            "id": f"link_{uuid.uuid4().hex[:8]}", "run_id": run["id"], "claim_id": claim_id,
            "source_id": source_id, "excerpt_id": excerpt_id, "relation_type": "supports",
            "confidence": 0.8, "rationale": "reported", "created_at": now,
        }
    )
    # Unsupported claim should be flagged, not presented as a conclusion citation.
    ResearchClaimRepository.insert(
        {
            "id": f"claim_{uuid.uuid4().hex[:8]}", "run_id": run["id"], "hypothesis_id": None,
            "statement": "An unsupported guess.", "status": "draft", "evidence_ids": [],
            "confidence": 0.0, "created_at": now, "updated_at": now,
        }
    )
    ExperimentResultRepository.insert(
        {
            "id": f"exp_result_{uuid.uuid4().hex[:8]}", "experiment_run_id": "er", "protocol_id": "p",
            "run_id": run["id"], "status": "completed", "summary": "treatment beats baseline",
            "metrics": {"metric_name": "recall", "rows": [{"strategy": "bm25", "recall": 0.6}, {"strategy": "dpr", "recall": 0.8}]},
            "exit_code": 0, "stdout": "", "stderr": "", "artifacts": [], "created_at": now,
        }
    )

    mode = paper_assembly_service.detect_mode(run)
    assert mode == "paper"
    doc = paper_assembly_service.assemble(run, mode=mode, narrative="discussion prose here")

    assert "## 参考文献" in doc
    assert "[1]" in doc  # inline citation and reference entry
    assert "Dense retrieval improves recall over BM25. [1]" in doc
    assert "An unsupported guess." in doc  # present but under limitations
    assert "## 7. 局限性与未决问题" in doc
    assert "| strategy | recall |" in doc  # real metrics table
    assert "discussion prose here" in doc
    assert "`ref_" in doc
    assert "## 追溯附录" in doc
    assert claim_id in doc
    assert excerpt_id in doc
    assert "负结果与有效性威胁" in doc
    assert grounding_audit_service.audit_report(doc)["passed"] is True


def test_survey_mode_detected_for_survey_goal():
    run = _make_run("调研 GitHub 上的多 Agent 框架现状")
    assert paper_assembly_service.detect_mode(run) == "survey"
    doc = paper_assembly_service.assemble(run)
    assert doc.startswith("# 调研报告")
    assert "`research_report`" in doc


def test_delivery_status_only_promotes_after_quality_gate():
    report = "# Paper\n\n**交付等级:** `thesis_draft`\n"
    assert "`thesis_draft`" in ReportService._promote_delivery_status(report, {"passed": True, "publication_ready": False})
    assert "`publishable_manuscript`" in ReportService._promote_delivery_status(report, {"passed": True, "publication_ready": True})


def test_paper_helpers_deduplicate_and_summarize_publishable_experiment():
    records = [
        {"id": "draft", "statement": "Same claim", "status": "draft"},
        {"id": "supported", "statement": "  Same   claim ", "status": "supported"},
    ]
    assert paper_assembly_service._dedupe_records(records, "statement", "status")[0]["id"] == "supported"

    summary = paper_assembly_service._primary_experiment_summary([{
        "metrics": {
            "publishable": True, "evaluated_query_count": 20,
            "rows": [
                {"strategy": "no_split", "mrr_at_10": 0.5},
                {"strategy": "fixed_100_overlap_30", "mrr_at_10": 1.0},
            ],
            "statistical_analysis": {"mean_delta": 0.5, "confidence_interval_95": [0.5, 0.5]},
            "reproduction": {"passed": True},
        },
    }])
    assert "MRR@10=1.0" in summary
    assert "干净目录复现=通过" in summary
