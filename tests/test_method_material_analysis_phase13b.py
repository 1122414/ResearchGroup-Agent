import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from backend.app.services.artifact_manifest_service import artifact_manifest_service
from backend.app.services.method_material_analysis_service import method_material_analysis_service
from backend.app.services.research_analysis_service import research_analysis_service
from backend.app.services.research_state_service import research_state_service
from backend.app.storage import init_db
from backend.app.storage.repositories import ResearchBriefRepository, RunRepository


@pytest.fixture(autouse=True)
def _db():
    init_db()


def _run(tmp_path, family: str, texts: list[str]) -> tuple[dict, dict]:
    run_id = f"run_method_material_{uuid.uuid4().hex[:8]}"
    run_dir = tmp_path / run_id
    input_dir = run_dir / "inputs"
    input_dir.mkdir(parents=True)
    artifact_manifest_service.initialize(run_dir, run_id=run_id, display_name="method material")
    now = datetime.now().isoformat()
    run = {
        "id": run_id, "research_goal": "分析真实材料", "artifact_dir": str(run_dir),
        "status": "created", "created_at": now, "updated_at": now,
    }
    RunRepository.insert(run)
    research_state_service.ensure_initialized(run)
    ResearchBriefRepository.update(
        run_id, research_question="真实材料支持何种限定解释？", methodology_family=family,
        methodology_profile={"family": family, "epistemic_mode": "interpretation"},
        ethics_plan={"required": False, "status": "not_required", "data_sensitivity": "public material"},
    )
    records = []
    for index, text in enumerate(texts, 1):
        path = input_dir / f"source_{index}.txt"
        path.write_text(text, encoding="utf-8")
        records.append({
            "id": f"material_{index:04d}", "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "declared_provenance": f"archive_{index}",
        })
    return {"id": "analysis", "run_id": run_id}, {"source_records": records}


@pytest.mark.asyncio
async def test_qualitative_raw_text_is_coded_with_code_owned_segment_hashes(tmp_path, monkeypatch):
    task, manifest = _run(tmp_path, "qualitative", ["Participant describes trust but also a concrete risk."])

    async def fake_ask(stage, _family, payload, _task):
        if stage == "reviewer":
            return {"approved": True, "feedback": "IDs and negative case checked", "checked_ids": ["seg_0001"]}
        assert payload["segments"][0]["text"].startswith("Participant")
        return {
            "codebook": [
                {"code": "trust", "definition": "expressed reliance"},
                {"code": "risk", "definition": "expressed concern"},
            ],
            "coding": [{"segment_id": "seg_0001", "codes": ["trust", "risk", "invented_code"]}],
            "negative_case_segment_ids": ["seg_0001", "missing"],
            "reflexivity_statement": "Model-assisted coding is bounded to supplied text.",
            "saturation_assessment": "Single-source information power is limited.",
            "limitations": ["One supplied source"],
        }

    monkeypatch.setattr(method_material_analysis_service, "_ask", fake_ask)
    package = await method_material_analysis_service.build_for_task(task, manifest)
    artifact = research_analysis_service.analyze_for_task(task, manifest, package)

    assert package["coded_segments"][0]["codes"] == ["trust", "risk"]
    assert package["negative_cases"] == ["seg_0001"]
    assert package["coded_segments"][0]["text_sha256"] == hashlib.sha256(
        "Participant describes trust but also a concrete risk.".encode()
    ).hexdigest()
    assert all(item["status"] == "passed" for item in artifact["method_checks"].values())
    assert artifact["method_package_artifact_sha256"] == hashlib.sha256(
        Path(artifact["method_package_artifact"]).read_bytes()
    ).hexdigest()


@pytest.mark.asyncio
async def test_humanities_interpretation_drops_unknown_sources_and_requires_independent_review(tmp_path, monkeypatch):
    task, manifest = _run(tmp_path, "humanities", ["Primary source A", "Primary source B"])

    async def fake_ask(stage, _family, _payload, _task):
        if stage == "reviewer":
            return {"approved": False, "feedback": "Alternative context remains unchecked", "checked_ids": ["material_0001"]}
        return {
            "source_criticisms": [
                {"source_id": "material_0001", "criticism": "Authorship checked"},
                {"source_id": "material_0002", "criticism": "Transmission checked"},
            ],
            "historical_or_textual_context": "Bounded context", "interpretive_framework": "Hermeneutic comparison",
            "interpretations": [
                {"statement": "Bounded reading", "source_ids": ["material_0001", "material_0002", "missing"]},
            ],
            "counterarguments": [{"statement": "Alternative reading", "source_ids": ["material_0002"]}],
            "limitations": ["Small corpus"],
        }

    monkeypatch.setattr(method_material_analysis_service, "_ask", fake_ask)
    package = await method_material_analysis_service.build_for_task(task, manifest)
    artifact = research_analysis_service.analyze_package(package, "humanities", [item["sha256"] for item in manifest["source_records"]])

    assert package["interpretations"][0]["source_ids"] == ["material_0001", "material_0002"]
    assert artifact["method_checks"]["independent_interpretive_review"]["status"] == "failed"


@pytest.mark.asyncio
async def test_sensitive_material_is_not_sent_to_external_model_without_explicit_approval(tmp_path, monkeypatch):
    task, manifest = _run(tmp_path, "qualitative", ["Sensitive participant transcript"])
    ResearchBriefRepository.update(
        task["run_id"],
        ethics_plan={"required": True, "status": "approved", "data_sensitivity": "sensitive personal data"},
    )

    async def forbidden(*_args):
        raise AssertionError("sensitive material must not reach the model")

    monkeypatch.setattr(method_material_analysis_service, "_ask", forbidden)

    assert await method_material_analysis_service.build_for_task(task, manifest) is None


@pytest.mark.asyncio
async def test_systematic_review_pool_is_independently_screened_and_grounded(tmp_path, monkeypatch):
    task, manifest = _run(tmp_path, "systematic_review", [])
    run = RunRepository.get_by_id(task["run_id"])
    pool_path = Path(run["artifact_dir"]) / "review_pool.json"
    pool_path.write_text(json.dumps({
        "schema_version": "systematic-review-pool-v1",
        "studies": [
            {"id": "p1", "title": "Included", "doi": "10.1000/p1", "passages": [{"text": "results"}]},
            {"id": "p2", "title": "Excluded", "doi": "10.1000/p2", "passages": [{"text": "methods"}]},
        ],
        "deduplication_log": {"input_count": 2, "deduplicated_count": 2, "duplicate_ids": []},
    }), encoding="utf-8")
    manifest["source_records"].append({
        "id": "systematic_review_pool", "path": str(pool_path),
        "sha256": hashlib.sha256(pool_path.read_bytes()).hexdigest(),
    })

    async def fake_ask(stage, _family, payload, _task):
        assert {item["id"] for item in payload["studies"]} == {"p1", "p2"}
        return {
            "decisions": [
                {"study_id": "p1", "decision": "include", "reason": f"{stage} eligible"},
                {"study_id": "p2", "decision": "exclude", "reason": f"{stage} ineligible"},
                {"study_id": "invented", "decision": "include", "reason": "must be dropped"},
            ],
            "quality_appraisals": [{"study_id": "p1", "rating": "low risk", "rationale": "checked"}],
            "synthesis_method": "narrative synthesis", "feedback": f"{stage} completed independently",
        }

    monkeypatch.setattr(method_material_analysis_service, "_ask", fake_ask)
    package = await method_material_analysis_service.build_for_task(task, manifest)
    artifact = research_analysis_service.analyze_package(
        package, "systematic_review", [manifest["source_records"][0]["sha256"]]
    )

    assert len(package["screening_records"]) == 4
    assert {item["study_id"] for item in package["screening_records"]} == {"p1", "p2"}
    assert package["screening_conflicts"] == []
    assert all(item["status"] == "passed" for item in artifact["method_checks"].values())
