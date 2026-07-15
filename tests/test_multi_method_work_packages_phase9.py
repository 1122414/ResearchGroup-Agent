import hashlib
import json
import uuid
from datetime import datetime

import pytest

from backend.app.models.task import TaskType
from backend.app.services.artifact_manifest_service import artifact_manifest_service
from backend.app.services.research_material_service import research_material_service
from backend.app.services.research_method_registry_service import research_method_registry_service
from backend.app.services.research_state_service import research_state_service
from backend.app.services.scientific_quality_gate_service import scientific_quality_gate_service
from backend.app.services.task_decomposer import task_decomposer
from backend.app.storage import init_db
from backend.app.storage.repositories import ResearchBriefRepository, RunRepository


@pytest.fixture(autouse=True)
def _db():
    init_db()


def _brief(family: str) -> dict:
    return {
        "methodology_family": family,
        "methodology_profile": {"family": family, "epistemic_mode": "interpretation"},
        "resource_plan": [{
            "resource_type": "primary_material", "required": True, "status": "available",
            "evidence": "用户声明拥有研究使用权",
        }],
        "ethics_plan": {"required": False, "status": "not_required", "approval_reference": ""},
        "thesis_requirements": {"status": "confirmed"},
    }


@pytest.mark.parametrize("family", sorted(research_method_registry_service.ANALYSIS_CHECKS))
def test_each_method_family_has_distinct_analysis_quality_contract(family):
    brief = _brief(family)
    requirements = research_method_registry_service.requirements_for(brief)["result_analysis"]
    checks = {name: {"status": "passed", "evidence": "artifact locator"} for name in requirements["required_method_checks"]}
    latest = {"analysis_artifact": {
        "family": family, "input_hashes": ["a" * 64], "procedure": "frozen procedure",
        "findings": ["bounded finding"], "limitations": ["declared limitation"], "method_checks": checks,
    }}

    assert research_method_registry_service.validate_task(
        {"task_type": "result_analysis"}, latest, brief
    ) == []
    assert requirements["required_method_checks"]


def test_method_specific_gate_fails_closed_when_one_required_check_is_missing():
    brief = _brief("qualitative")
    latest = {"analysis_artifact": {
        "family": "qualitative", "input_hashes": ["b" * 64], "procedure": "coding",
        "findings": ["theme"], "limitations": ["sample boundary"],
        "method_checks": {
            name: {"status": "passed", "evidence": "audit trail"}
            for name in research_method_registry_service.ANALYSIS_CHECKS["qualitative"]
            if name != "negative_cases"
        },
    }}

    issues = research_method_registry_service.validate_task(
        {"task_type": "result_analysis"}, latest, brief
    )

    assert "analysis_artifact.method_checks.negative_cases_not_passed" in issues


def test_research_design_requires_method_fit_quality_controls_and_deviation_policy():
    brief = _brief("humanities")
    valid = {"method_package": {
        "family": "humanities", "study_design": "bounded archival interpretation",
        "sampling_or_corpus_plan": "declared archive and date range",
        "data_or_material_protocol": "source criticism and version capture",
        "analysis_plan": "contextual interpretation with counterargument analysis",
        "quality_controls": ["source triangulation", "negative evidence"],
        "stopping_rule": "corpus boundary exhausted", "deviation_policy": "log and review every deviation",
    }}
    assert research_method_registry_service.validate_task(
        {"task_type": "research_design"}, valid, brief
    ) == []

    invalid = {"method_package": {**valid["method_package"], "family": "computational", "quality_controls": []}}
    issues = research_method_registry_service.validate_task(
        {"task_type": "research_design"}, invalid, brief
    )
    assert "methodology_family_mismatch" in issues
    assert "method_package.quality_controls_insufficient" in issues


def test_user_materials_are_hashed_and_registered_without_llm_generated_raw_data(tmp_path):
    now = datetime.now().isoformat()
    run_id = f"run_material_{uuid.uuid4().hex[:8]}"
    run_dir = tmp_path / run_id
    input_dir = run_dir / "inputs"
    input_dir.mkdir(parents=True)
    material_path = input_dir / "01_primary.txt"
    material_path.write_text("真实一手材料", encoding="utf-8")
    attachments_path = input_dir / "attachments.json"
    attachments_path.write_text(json.dumps([{
        "name": "primary.txt", "mime_type": "text/plain", "path": str(material_path),
        "extracted_markdown": "真实一手材料",
    }], ensure_ascii=False), encoding="utf-8")
    artifact_manifest_service.initialize(run_dir, run_id=run_id, display_name="material test")
    RunRepository.insert({
        "id": run_id, "research_goal": "分析真实一手材料", "artifact_dir": str(run_dir),
        "status": "created", "created_at": now, "updated_at": now,
    })
    research_state_service.ensure_initialized(RunRepository.get_by_id(run_id))
    ResearchBriefRepository.update(
        run_id,
        resource_plan=_brief("humanities")["resource_plan"],
        ethics_plan=_brief("humanities")["ethics_plan"],
        methodology_family="humanities",
        methodology_profile=_brief("humanities")["methodology_profile"],
    )

    manifest = research_material_service.ingest_for_task({"id": "task_material", "run_id": run_id})

    assert manifest["completeness"] == "complete"
    assert len(manifest["source_records"]) == 1
    record = manifest["source_records"][0]
    assert record["provenance"] == "user_supplied_run_attachment"
    assert record["sha256"] == hashlib.sha256(material_path.read_bytes()).hexdigest()
    assert "用户声明拥有研究使用权" in record["authorization_evidence"]
    assert manifest["artifact"] in {
        item["path"] for item in artifact_manifest_service.read(run_dir)["artifacts"]
    }


def test_data_acquisition_quality_gate_rejects_unregistered_or_tampered_material(tmp_path, monkeypatch):
    run_id = "run_tamper"
    monkeypatch.setattr(ResearchBriefRepository, "get_by_run", lambda _run_id: _brief("humanities"))
    issues = research_method_registry_service.validate_task(
        {"task_type": "data_acquisition"},
        {"material_manifest": {
            "frozen_at": "now", "collection_log": "log", "completeness": "complete",
            "source_records": [{
                "id": "m1", "path": str(tmp_path / "missing.txt"), "sha256": "bad",
                "provenance": "claimed", "authorization_evidence": "claimed", "size_bytes": 1,
            }],
        }},
        _brief("humanities"),
    )
    assert "material_manifest.source_records[0].sha256_invalid" in issues
    assert "material_manifest_missing" not in issues


def test_noncomputational_decomposition_uses_method_neutral_work_packages():
    tasks = [
        {"task_type": "system_design", "title": "系统设计", "description": ""},
        {"task_type": "experiment_design", "title": "实验", "description": ""},
    ]
    converted = task_decomposer._respect_methodology_capability(
        tasks,
        {"methodology_family": "systematic_review", "methodology_profile": {"epistemic_mode": "evidence_synthesis"}},
    )
    assert [item["task_type"] for item in converted] == ["research_design", "data_acquisition"]
    assert "不得由 LLM 补造" in converted[1]["description"]


def test_public_task_model_exposes_method_neutral_task_types():
    assert TaskType.research_design.value == "research_design"
    assert TaskType.data_acquisition.value == "data_acquisition"
