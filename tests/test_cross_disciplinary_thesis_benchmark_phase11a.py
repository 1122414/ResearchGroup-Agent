from __future__ import annotations

import json
from pathlib import Path

from backend.app.services.artifact_manifest_service import artifact_manifest_service
from backend.app.services.cross_disciplinary_thesis_benchmark_service import (
    CrossDisciplinaryThesisBenchmarkService,
)


def _review() -> dict:
    return {
        "quality_gates": {
            "passed": True,
            "layers": {
                "independent_review": {
                    "passed": True,
                    "simulation": False,
                    "reviewer": "independent_reviewer_model",
                }
            },
        }
    }


def _valid_snapshot(tmp_path: Path, run_id: str = "run_real") -> dict:
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / ".run_id").write_text(run_id, encoding="utf-8")
    artifact_manifest_service.initialize(run_dir, run_id=run_id, display_name="真实课题")
    input_path = run_dir / "inputs" / "dataset.csv"
    input_path.parent.mkdir()
    input_path.write_text("id,value\n1,2\n", encoding="utf-8")
    analysis_path = run_dir / "analysis" / "result.json"
    analysis_path.parent.mkdir()
    analysis_path.write_text('{"result": 2}', encoding="utf-8")
    report = "# 真实硕士论文\n\n**交付等级:** `master_thesis`\n\n## 参考文献\n\n[1] Source"
    report_path = run_dir / "final_report.md"
    report_path.write_text(report, encoding="utf-8")
    artifact_manifest_service.register(run_dir, kind="input", path=str(input_path))
    artifact_manifest_service.register(run_dir, kind="method_analysis", path=str(analysis_path))
    artifact_manifest_service.register(run_dir, kind="report", path=str(report_path))
    tasks = [
        {
            "id": f"task_{task_type}", "task_type": task_type,
            "status": "completed", "review_result": _review(),
        }
        for task_type in (
            "literature_survey", "research_design", "data_acquisition",
            "result_analysis", "thesis_chapter", "report_writing",
        )
    ]
    source = {
        "id": "source_1", "doi": "10.1234/verified.1", "url": None,
        "metadata": {"citation_eligible": True},
    }
    return {
        "run": {"id": run_id, "status": "completed", "artifact_dir": str(run_dir)},
        "brief": {
            "methodology_family": "quantitative",
            "discipline": {"broad_field": "social_science", "field": "education"},
            "thesis_requirements": {
                "status": "confirmed", "required_chapters": ["分析"],
                "minimum_references": 1, "minimum_supported_claims": 1,
            },
            "ethics_plan": {"required": False, "status": "not_required"},
            "resource_plan": [{"required": True, "status": "available"}],
        },
        "tasks": tasks,
        "evidence": {
            "sources": [source],
            "excerpts": [{
                "id": "passage_1", "source_id": "source_1",
                "excerpt_type": "fulltext", "excerpt": "verified passage",
            }],
            "claims": [], "assessments": [], "links": [],
        },
        "outputs": [
            {"output_type": "final_report", "content": report},
            {
                "output_type": "scientific_quality_gate",
                "content": json.dumps({
                    "passed": True, "master_thesis_ready": True,
                    "deliverable_level": "master_thesis", "master_thesis_blockers": [],
                    "thesis_quality": {"passed": True},
                }),
            },
        ],
        "usages": [{"provider": "openai_compatible", "model": "real-model", "success": True}],
        "experiments": [],
        "claims": [{"id": "claim_1", "status": "supported"}],
        "manifest": artifact_manifest_service.read(run_dir),
    }


def _spec(run_id: str | None = "run_real") -> dict:
    return {
        "id": "social", "paradigm": "social_science_quantitative",
        "allowed_method_families": ["quantitative"], "run_id": run_id,
    }


def test_pending_registry_truthfully_reports_zero_of_five():
    service = CrossDisciplinaryThesisBenchmarkService()
    path = Path(__file__).parents[1] / "benchmarks" / "thesis_projects.json"

    result = service.run(path)

    assert result["passed"] is False
    assert result["completed_projects"] == 0
    assert result["required_projects"] == 5
    assert all(item["issues"] == ["run_id_not_assigned"] for item in result["projects"])


def test_unassigned_run_is_rejected_without_loading_database():
    result = CrossDisciplinaryThesisBenchmarkService().audit_project(_spec(None))

    assert result["passed"] is False
    assert result["issues"] == ["run_id_not_assigned"]


def test_fully_consistent_real_snapshot_passes_project_audit(tmp_path, monkeypatch):
    service = CrossDisciplinaryThesisBenchmarkService()
    snapshot = _valid_snapshot(tmp_path)
    monkeypatch.setattr(
        service, "_recompute_quality",
        lambda _data, _report: {"master_thesis_ready": True, "thesis_quality": {"passed": True}},
    )

    result = service.audit_project(_spec(), snapshot)

    assert result["passed"] is True
    assert result["issues"] == []


def test_mock_provider_and_missing_external_passages_are_fail_closed(tmp_path, monkeypatch):
    service = CrossDisciplinaryThesisBenchmarkService()
    snapshot = _valid_snapshot(tmp_path)
    snapshot["usages"][0]["provider"] = "mock"
    snapshot["evidence"]["excerpts"] = []
    monkeypatch.setattr(
        service, "_recompute_quality",
        lambda _data, _report: {"master_thesis_ready": True, "thesis_quality": {"passed": True}},
    )

    result = service.audit_project(_spec(), snapshot)

    assert "mock_or_failed_llm_usage" in result["issues"]
    assert "insufficient_verified_external_sources:0/1" in result["issues"]


def test_changed_input_hash_is_rejected(tmp_path, monkeypatch):
    service = CrossDisciplinaryThesisBenchmarkService()
    snapshot = _valid_snapshot(tmp_path)
    run_dir = Path(snapshot["run"]["artifact_dir"])
    (run_dir / "inputs" / "dataset.csv").write_text("changed", encoding="utf-8")
    monkeypatch.setattr(
        service, "_recompute_quality",
        lambda _data, _report: {"master_thesis_ready": True, "thesis_quality": {"passed": True}},
    )

    result = service.audit_project(_spec(), snapshot)

    assert "real_input_artifact_missing_or_invalid" in result["issues"]


def test_duplicate_run_ids_cannot_satisfy_five_paradigms(tmp_path, monkeypatch):
    service = CrossDisciplinaryThesisBenchmarkService()
    projects = [
        {"id": paradigm, "paradigm": paradigm, "run_id": "same_run"}
        for paradigm in sorted(service.REQUIRED_PARADIGMS)
    ]
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"projects": projects}), encoding="utf-8")
    monkeypatch.setattr(
        service, "audit_project",
        lambda spec: service._result(
            spec, issues=[], run_id="same_run", method_family="quantitative", broad_field="same",
        ),
    )

    result = service.run(registry)

    assert result["passed"] is False
    assert "duplicate_run_ids" in result["global_issues"]
    assert "insufficient_method_family_diversity" in result["global_issues"]
    assert "insufficient_discipline_diversity" in result["global_issues"]
