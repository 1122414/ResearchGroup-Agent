import hashlib
import json
import uuid
from datetime import datetime

import pytest

from backend.app.services.artifact_manifest_service import artifact_manifest_service
from backend.app.services.research_analysis_service import research_analysis_service
from backend.app.services.research_method_registry_service import research_method_registry_service
from backend.app.services.research_state_service import research_state_service
from backend.app.services.review_service import review_service
from backend.app.services.scientific_quality_gate_service import scientific_quality_gate_service
from backend.app.storage import init_db
from backend.app.storage.repositories import ResearchBriefRepository, ResearchClaimRepository, RunRepository


@pytest.fixture(autouse=True)
def _db():
    init_db()


def _base(family: str) -> dict:
    return {"schema_version": "research-method-data-v1", "family": family, "limitations": ["冻结样本边界"]}


def _packages() -> dict[str, dict]:
    numeric = {
        "records": [
            {"group": "baseline", "outcome": 1}, {"group": "baseline", "outcome": 2},
            {"group": "treatment", "outcome": 3}, {"group": "treatment", "outcome": 4},
        ],
        "group_field": "group", "outcome_field": "outcome",
        "baseline_group": "baseline", "treatment_group": "treatment",
    }
    return {
        "quantitative": {
            **_base("quantitative"), **numeric, "measurement_definition": "validated scale score",
            "missing_data_policy": "report and do not impute",
        },
        "computational": {
            **_base("computational"), **numeric, "data_split": "frozen train/test split",
            "reproduction_runs": [2.0, 2.0],
        },
        "experimental": {
            **_base("experimental"), **numeric, "control_description": "negative control",
            "protocol_deviations": [],
        },
        "qualitative": {
            **_base("qualitative"),
            "source_materials": [
                {"id": "i1", "locator": "transcript:1", "sha256": "1" * 64},
                {"id": "i2", "locator": "transcript:2", "sha256": "2" * 64},
            ],
            "coded_segments": [
                {"id": "s1", "source_id": "i1", "text_sha256": "3" * 64, "codes": ["trust", "risk"]},
                {"id": "s2", "source_id": "i2", "text_sha256": "4" * 64, "codes": ["trust"]},
                {"id": "s3", "source_id": "i2", "text_sha256": "5" * 64, "codes": ["risk"]},
            ],
            "codebook": [
                {"code": "trust", "definition": "declared definition"},
                {"code": "risk", "definition": "declared risk definition"},
            ],
            "audit_trail": [
                {"coder_id": "coder_1", "action": "initial coding"},
                {"coder_id": "coder_2", "action": "independent review"},
            ], "negative_cases": ["s3"],
            "reflexivity_statement": "researcher position declared",
            "saturation_assessment": "information power assessed",
            "independent_review": {"approved": True, "checked_ids": ["s1", "s2", "s3"]},
        },
        "systematic_review": {
            **_base("systematic_review"),
            "studies": [{"id": "p1", "title": "Verified Study", "doi": "10.1000/p1"}],
            "screening_records": [
                {"study_id": "p1", "reviewer": "r1", "stage": "title", "decision": "include"},
                {"study_id": "p1", "reviewer": "r2", "stage": "title", "decision": "include"},
            ],
            "deduplication_log": {"input_count": 2, "deduplicated_count": 1, "duplicate_ids": ["dup1"]},
            "quality_appraisals": [{"study_id": "p1", "rating": "low risk"}],
            "synthesis_method": "narrative synthesis",
        },
        "humanities": {
            **_base("humanities"),
            "primary_sources": [
                {"id": "a", "provenance": "archive_a", "locator": "archive:a", "sha256": "6" * 64, "criticism": "authorship and date checked"},
                {"id": "b", "provenance": "archive_b", "locator": "archive:b", "sha256": "7" * 64, "criticism": "edition and transmission checked"},
            ],
            "historical_or_textual_context": "bounded historical context",
            "interpretive_framework": "declared hermeneutic framework",
            "counterarguments": [{"statement": "alternative reading", "source_ids": ["b"]}],
            "interpretations": [{"statement": "bounded interpretation", "source_ids": ["a", "b"]}],
            "independent_review": {"approved": True, "checked_ids": ["a", "b"]},
        },
        "theoretical": {
            **_base("theoretical"), "definitions": ["D1"], "assumptions": ["A1"],
            "proof_steps": [
                {"id": "p1", "depends_on": [], "justification": "definition D1"},
                {"id": "p2", "depends_on": ["p1"], "justification": "lemma application"},
            ],
            "counterexample_search": "searched boundary cases; none under assumptions",
        },
        "design_science": {
            **_base("design_science"), "requirements_trace": [{"requirement": "r1", "artifact": "a1"}],
            "artifact": {"id": "a1", "description": "prototype"},
            "evaluations": [{"criterion": "utility", "result": "met"}],
            "alternatives": [{"id": "a0", "reason_rejected": "lower utility"}],
        },
        "mixed_methods": {
            **_base("mixed_methods"),
            "component_results": [
                {"family": "quantitative", "quality_passed": True},
                {"family": "qualitative", "quality_passed": True},
            ],
            "integration_design": "convergent", "joint_display": [{"topic": "trust", "integrated": "converges"}],
            "discordances": [], "meta_inferences": ["components converge within frozen scope"],
        },
    }


@pytest.mark.parametrize("family", sorted(_packages()))
def test_deterministic_adapter_outputs_pass_its_method_specific_contract(family):
    artifact = research_analysis_service.analyze_package(_packages()[family], family, ["a" * 64])
    issues = research_method_registry_service.validate_task(
        {"task_type": "result_analysis"}, {"analysis_artifact": artifact},
        {"methodology_family": family, "methodology_profile": {"family": family}},
    )

    assert issues == []
    assert artifact["family"] == family
    assert artifact["input_hashes"] == ["a" * 64]
    assert all(item["status"] == "passed" for item in artifact["method_checks"].values())


def test_quantitative_adapter_computes_numbers_in_code_not_language_model():
    artifact = research_analysis_service.analyze_package(
        _packages()["quantitative"], "quantitative", ["b" * 64]
    )
    finding = artifact["findings"][0]
    assert finding["mean_difference"] == 2.0
    assert finding["median_difference_sensitivity"] == 2.0
    assert finding["n_baseline"] == finding["n_treatment"] == 2
    assert finding["confidence_interval_95_normal"] is not None


def test_wrong_family_or_unversioned_package_is_blocked():
    wrong = research_analysis_service.analyze_package(
        _packages()["qualitative"], "humanities", ["c" * 64]
    )
    missing = research_analysis_service.analyze_package({}, "qualitative", ["d" * 64])
    assert wrong["findings"][0]["reason"] == "method_data_package_family_mismatch"
    assert missing["findings"][0]["reason"] == "method_data_package_missing_or_schema_invalid"
    assert wrong["method_checks"] == missing["method_checks"] == {}


def test_theoretical_adapter_rejects_cycles_and_unknown_dependencies():
    package = {
        **_packages()["theoretical"],
        "proof_steps": [
            {"id": "p1", "depends_on": ["p2"], "justification": "circular"},
            {"id": "p2", "depends_on": ["p1", "unknown"], "justification": "circular"},
        ],
    }
    artifact = research_analysis_service.analyze_package(package, "theoretical", ["e" * 64])
    assert artifact["method_checks"]["dependency_graph"]["status"] == "failed"
    issues = research_method_registry_service.validate_task(
        {"task_type": "result_analysis"}, {"analysis_artifact": artifact},
        {"methodology_family": "theoretical", "methodology_profile": {"family": "theoretical"}},
    )
    assert "analysis_artifact.method_checks.dependency_graph_not_passed" in issues


def test_systematic_review_adapter_rejects_single_reviewer_screening():
    package = {
        **_packages()["systematic_review"],
        "screening_records": [
            {"study_id": "p1", "reviewer": "r1", "stage": "title", "decision": "include"},
        ],
    }
    artifact = research_analysis_service.analyze_package(package, "systematic_review", ["f" * 64])
    assert artifact["method_checks"]["dual_screening"]["status"] == "failed"


def test_qualitative_adapter_rejects_unhashed_or_unknown_source_segments():
    package = {
        **_packages()["qualitative"],
        "coded_segments": [{"id": "s1", "source_id": "invented", "text_sha256": "bad", "codes": ["trust"]}],
    }

    artifact = research_analysis_service.analyze_package(package, "qualitative", ["a" * 64])

    assert artifact["method_checks"]["material_traceability"]["status"] == "failed"


def test_systematic_review_rejects_screening_of_unregistered_study():
    package = {
        **_packages()["systematic_review"],
        "screening_records": [
            {"study_id": "invented", "reviewer": "r1", "stage": "title", "decision": "include"},
            {"study_id": "invented", "reviewer": "r2", "stage": "title", "decision": "include"},
        ],
    }

    artifact = research_analysis_service.analyze_package(package, "systematic_review", ["b" * 64])

    assert artifact["method_checks"]["screening_integrity"]["status"] == "failed"
    assert artifact["method_checks"]["appraisal_coverage"]["status"] == "failed"


def test_systematic_review_rejects_registered_study_that_was_never_screened():
    package = {
        **_packages()["systematic_review"],
        "studies": [
            {"id": "p1", "title": "First Study", "doi": "10.1000/p1"},
            {"id": "p2", "title": "Omitted Study", "doi": "10.1000/p2"},
        ],
    }

    artifact = research_analysis_service.analyze_package(package, "systematic_review", ["b" * 64])

    assert artifact["method_checks"]["screening_integrity"]["status"] == "failed"


def test_humanities_adapter_rejects_untraceable_interpretation():
    package = {
        **_packages()["humanities"],
        "interpretations": [{"statement": "invented reading", "source_ids": ["missing"]}],
    }

    artifact = research_analysis_service.analyze_package(package, "humanities", ["c" * 64])

    assert artifact["method_checks"]["interpretation_traceability"]["status"] == "failed"


def test_analysis_reads_only_hashed_method_package_and_registers_artifact(tmp_path):
    now = datetime.now().isoformat()
    run_id = f"run_analysis_{uuid.uuid4().hex[:8]}"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    package_path = run_dir / "quantitative_package.json"
    package_path.write_text(json.dumps({
        "method_data_package": _packages()["quantitative"],
    }, ensure_ascii=False), encoding="utf-8")
    digest = hashlib.sha256(package_path.read_bytes()).hexdigest()
    artifact_manifest_service.initialize(run_dir, run_id=run_id, display_name="analysis test")
    RunRepository.insert({
        "id": run_id, "research_goal": "定量分析", "artifact_dir": str(run_dir),
        "status": "created", "created_at": now, "updated_at": now,
    })
    research_state_service.ensure_initialized(RunRepository.get_by_id(run_id))
    ResearchBriefRepository.update(
        run_id, methodology_family="quantitative",
        methodology_profile={"family": "quantitative", "epistemic_mode": "estimation"},
    )
    manifest = {"source_records": [{"path": str(package_path), "sha256": digest}]}

    artifact = research_analysis_service.analyze_for_task(
        {"id": "task_analysis", "run_id": run_id}, manifest,
    )

    assert artifact["findings"][0]["mean_difference"] == 2.0
    assert artifact["input_hashes"] == [digest]
    assert artifact["artifact"] in {
        item["path"] for item in artifact_manifest_service.read(run_dir)["artifacts"]
    }
    claims = research_analysis_service.claims_for_artifact(artifact)
    provenance = claims[0]["provenance"]
    assert scientific_quality_gate_service._method_claim_provenance_issues(
        {"run_id": run_id}, provenance
    ) == []

    claim_id = f"claim_{uuid.uuid4().hex[:8]}"
    ResearchClaimRepository.insert({
        "id": claim_id, "run_id": run_id, "statement": claims[0]["statement"],
        "status": "draft", "evidence_ids": [], "confidence": 0,
        "created_at": now, "updated_at": now,
    })
    review_service._promote_artifact_claims({"run_id": run_id}, {"claims": claims})
    promoted = ResearchClaimRepository.get_by_id(claim_id)
    assert promoted["status"] == "supported"
    assert provenance["analysis_artifact"] in promoted["evidence_ids"]
    assert scientific_quality_gate_service._artifact_backed_research_claim(run_id, promoted) is True
