import uuid
from datetime import datetime

import pytest

from backend.app.services.research_contract_service import research_contract_service
from backend.app.services.research_methodology_service import research_methodology_service
from backend.app.services.scientific_quality_gate_service import scientific_quality_gate_service
from backend.app.services.research_state_service import research_state_service
from backend.app.services.task_decomposer import task_decomposer
from backend.app.storage import init_db
from backend.app.storage.repositories import (
    EvidenceRepository, ExperimentResultRepository, ResearchBriefRepository,
    ResearchClaimRepository, RunRepository, TaskRepository,
)


@pytest.fixture(autouse=True)
def _db():
    init_db()


def _contract(
    family: str = "qualitative",
    epistemic_mode: str = "interpretation",
    *,
    resource_status: str = "available",
    ethics_required: bool = False,
    ethics_status: str = "not_required",
    thesis_status: str = "confirmed",
) -> dict:
    hypotheses = []
    if epistemic_mode in {"hypothesis_testing", "estimation", "artifact_evaluation"}:
        hypotheses = [{
            "statement": "干预相对基线产生可检测差异", "rationale": "预注册比较",
            "treatment": "干预", "baseline": "基线", "conditions": ["同一评价条件"],
            "predicted_direction": "差异", "primary_metric": "主指标",
            "minimum_effect": "领域最小重要差异", "falsification_criterion": "区间未超过阈值",
        }]
    component_methods = ["qualitative", "quantitative"] if family == "mixed_methods" else []
    return {
        "research_type": "interpretive" if family in {"qualitative", "humanities"} else "empirical",
        "primary_question": "在明确材料范围和分析框架下，核心研究问题应如何得到可审计回答？",
        "objective": "形成方法、证据、分析和边界均可审计的硕士研究。",
        "subquestions": [
            {"id": "sq1", "question": "现有研究如何回答该问题？"},
            {"id": "sq2", "question": "本研究材料支持何种结论？"},
        ],
        "scope_in": ["冻结材料范围"], "scope_out": ["无证据外推"],
        "target_domain": "cross_disciplinary_test", "constraints": ["保留负面结果"],
        "expected_contribution": "给出受方法质量标准约束的新结论。",
        "novelty_criteria": ["相对既有研究存在可说明增量"],
        "data_availability": "材料状态由 resource_plan 逐项声明。",
        "ethics_risks": [], "success_criteria": ["所有核心结论可追溯"],
        "failure_criteria": ["关键材料缺失或质量标准未通过"],
        "discipline": {"broad_field": "humanities_and_sciences", "field": "test_field", "subfield": "test"},
        "methodology_profile": {
            "family": family, "epistemic_mode": epistemic_mode,
            "study_design": "method-appropriate bounded study", "unit_of_analysis": "primary material unit",
            "evidence_types": ["primary sources", "verified scholarly literature"],
            "data_collection_methods": ["documented acquisition protocol"],
            "analysis_methods": ["method-specific analysis"],
            "quality_criteria": ["traceability", "negative-case or counterargument analysis"],
            "component_methods": component_methods,
        },
        "resource_plan": [{
            "resource_type": "primary_material", "description": "研究所需一手材料", "required": True,
            "status": resource_status, "owner": "researcher_or_institution", "evidence": "inventory",
            "resolution": "提供材料清单与合法访问凭据",
        }],
        "ethics_plan": {
            "required": ethics_required, "status": ethics_status, "review_body": "IRB" if ethics_required else "",
            "approval_reference": "" if ethics_status != "approved" else "IRB-TEST",
            "data_sensitivity": "potentially sensitive" if ethics_required else "public material",
            "participant_risks": ["privacy"] if ethics_required else [],
        },
        "thesis_requirements": {
            "degree_level": "master", "institution": "test university", "programme": "test programme",
            "language": "zh-CN", "citation_style": "Chicago", "target_word_count": 30000,
            "minimum_references": 20, "minimum_supported_claims": 5,
            "required_chapters": ["引言", "文献综述", "方法", "分析", "讨论", "结论"],
            "status": thesis_status,
        },
        "hypotheses": hypotheses,
    }


@pytest.mark.parametrize(
    ("family", "mode"),
    [
        ("quantitative", "estimation"), ("qualitative", "interpretation"),
        ("computational", "hypothesis_testing"), ("systematic_review", "evidence_synthesis"),
        ("humanities", "interpretation"), ("theoretical", "proof_construction"),
        ("design_science", "artifact_evaluation"), ("mixed_methods", "theory_building"),
    ],
)
def test_contract_accepts_multiple_epistemic_and_methodological_families(family, mode):
    contract = _contract(family, mode)
    assert research_contract_service.validate(contract, contract["hypotheses"]) == []


def test_interpretive_and_theoretical_work_is_not_forced_to_invent_statistical_hypothesis():
    for family, mode in (("humanities", "interpretation"), ("theoretical", "proof_construction")):
        contract = _contract(family, mode)
        assert contract["hypotheses"] == []
        assert research_contract_service.validate(contract, []) == []


def test_research_and_complete_thesis_readiness_are_separate_gates():
    contract = _contract(thesis_status="not_provided")
    assessment = research_methodology_service.assess(contract)
    assert assessment["research_ready"] is True
    assert assessment["thesis_ready"] is False
    assert assessment["execution_mode"] == "autonomous"
    assert assessment["thesis_blockers"][0]["code"] == "institutional_thesis_requirements_unconfirmed"


def test_wet_lab_or_participant_work_blocks_without_resources_and_ethics_approval():
    contract = _contract(
        "experimental", "hypothesis_testing", resource_status="requires_human",
        ethics_required=True, ethics_status="pending",
    )
    assessment = research_methodology_service.assess(contract)
    codes = {item["code"] for item in assessment["research_blockers"]}
    assert assessment["research_ready"] is False
    assert assessment["execution_mode"] == "human_led"
    assert codes == {"resource_requires_human", "ethics_approval_required"}


def test_feasibility_profile_round_trips_and_prevents_freezing_blocked_contract():
    now = datetime.now().isoformat()
    run_id = f"run_method_{uuid.uuid4().hex[:8]}"
    run = {"id": run_id, "research_goal": "执行需要参与者的跨学科研究", "status": "created", "created_at": now, "updated_at": now}
    RunRepository.insert(run)
    research_state_service.ensure_initialized(run)
    contract = _contract(resource_status="missing")

    revised = research_contract_service.revise(run_id, contract)

    assert revised["ready"] is False
    assert revised["brief"]["approval_status"] == "blocked_resources"
    assert revised["brief"]["methodology_family"] == "qualitative"
    assert revised["brief"]["discipline"]["field"] == "test_field"
    assert revised["brief"]["feasibility_assessment"]["research_ready"] is False
    with pytest.raises(ValueError, match="尚不可冻结"):
        research_contract_service.freeze(run_id)


def test_noncomputational_method_replaces_fabricated_experiment_with_real_material_acquisition():
    tasks = [
        {"task_type": "literature_survey"},
        {"task_type": "experiment_design"},
        {"task_type": "result_analysis"},
        {"task_type": "report_writing"},
    ]
    filtered = task_decomposer._respect_methodology_capability(
        tasks, {"methodology_family": "humanities"}
    )
    assert {item["task_type"] for item in filtered} == {
        "literature_survey", "data_acquisition", "result_analysis", "report_writing",
    }


def test_report_can_pass_research_gate_without_being_mislabeled_complete_master_thesis(monkeypatch):
    contract = _contract(thesis_status="not_provided")
    monkeypatch.setattr(EvidenceRepository, "get_by_run", lambda _run_id: {
        "sources": [], "excerpts": [], "links": [], "claims": [], "assessments": [],
    })
    monkeypatch.setattr(ResearchClaimRepository, "get_by_run", lambda _run_id: [])
    monkeypatch.setattr(ResearchBriefRepository, "get_by_run", lambda _run_id: contract)
    monkeypatch.setattr(ExperimentResultRepository, "get_by_run", lambda _run_id: [])
    monkeypatch.setattr(TaskRepository, "get_all", lambda run_id=None: [])

    quality = scientific_quality_gate_service.evaluate_report(
        "run_method", "# 可核验研究报告\n\n## 参考文献\n", {"passed": True},
    )

    assert quality["passed"] is True
    assert quality["publication_ready"] is True
    assert quality["master_thesis_ready"] is False
    assert quality["deliverable_level"] == "research_report"
    assert quality["master_thesis_blockers"][0]["code"] == "institutional_thesis_requirements_unconfirmed"
