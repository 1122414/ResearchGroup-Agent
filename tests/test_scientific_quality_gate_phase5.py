import json

import pytest

from backend.app.core.config import settings
from backend.app.services.scientific_quality_gate_service import scientific_quality_gate_service
from backend.app.services.claim_entailment_service import claim_entailment_service
from backend.app.services.independent_reviewer_service import independent_reviewer_service
from backend.app.services.review_service import review_service
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


@pytest.mark.asyncio
async def test_single_study_significant_result_does_not_require_two_sources(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(EvidenceRepository, "get_by_run", lambda _run_id: _evidence())
    quality = await scientific_quality_gate_service.evaluate_task(
        {"id": "task_1", "run_id": "run_1", "task_type": "literature_survey"},
        {
            "summary": "source-specific result", "entailment_audit": {"checked": True},
            "claims": [{
                "statement": "该研究报告结构感知切分使 MRR 从 0.36 显著提升到 0.59。",
                "evidence_source_ids": ["source_1"], "evidence_passage_ids": ["passage_1"],
                "entailment_verdict": "entailed",
            }],
        },
    )
    assert quality["passed"] is True


@pytest.mark.asyncio
async def test_attributed_single_study_causal_wording_does_not_loop(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(EvidenceRepository, "get_by_run", lambda _run_id: _evidence())
    quality = await scientific_quality_gate_service.evaluate_task(
        {"id": "task_1", "run_id": "run_1", "task_type": "literature_survey"},
        {
            "summary": "source-specific result", "entailment_audit": {"checked": True},
            "claims": [{
                "statement": "该论文在其测试设置下报告重叠切分会导致相邻块重复。",
                "evidence_source_ids": ["source_1"], "evidence_passage_ids": ["passage_1"],
                "entailment_verdict": "entailed",
            }],
        },
    )
    assert quality["passed"] is True


def test_integrity_policy_scopes_single_source_claim_before_quality_gate():
    from backend.app.services.research_integrity_service import research_integrity_service

    claims = research_integrity_service._scope_single_source_claims(
        [{
                "statement": "重叠切分会导致相邻块重复。",
                "evidence_source_ids": ["source_1"],
                "evidence_passage_ids": ["passage_1"],
                "relation": "supports",
                "confidence": 0.8,
        }]
    )

    assert claims[0]["statement"].startswith("该研究在其设置下报告：")


@pytest.mark.asyncio
async def test_literature_gate_rejects_zero_verified_claims(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(EvidenceRepository, "get_by_run", lambda _run_id: _evidence())
    quality = await scientific_quality_gate_service.evaluate_task(
        {"id": "task_1", "run_id": "run_1", "task_type": "literature_survey"},
        {"summary": "only a narrative", "claims": [], "entailment_audit": {"checked": True}},
    )
    assert quality["passed"] is False
    assert "literature_review_without_verified_claim" in quality["layers"]["semantic"]["issues"]


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
    assert result["issues"][0]["target"] == "review_transport"


@pytest.mark.asyncio
async def test_independent_reviewer_repairs_truncated_output_with_compact_protocol(monkeypatch):
    calls = []

    class Reviewer:
        async def generate(self, prompt, **_kwargs):
            calls.append(prompt)
            if len(calls) == 1:
                return '{"approved":true,"issues":[],"summary":"unterminated'
            return '{"approved":true,"issues":[],"summary":"evidence is consistent"}'

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "llm_structured_repair_attempts", 1)
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.create_llm_provider",
        lambda: Reviewer(),
    )
    result = await independent_reviewer_service.review_task(
        {"id": "task_1", "run_id": "run_1", "task_type": "literature_survey"},
        {"claims": []}, {"excerpts": []},
    )
    assert result["approved"] is True
    assert len(calls) == 2
    assert "严格压缩" in calls[1]
    assert "unterminated" not in calls[1]


@pytest.mark.asyncio
async def test_independent_reviewer_uses_binary_fallback_without_rerunning_task(monkeypatch):
    calls = []

    class Reviewer:
        async def generate(self, prompt, **_kwargs):
            calls.append(prompt)
            if len(calls) < 3:
                return '{"approved":true'
            return '{"approved":true,"summary":"reproduction is consistent"}'

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "llm_structured_repair_attempts", 1)
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.create_llm_provider",
        lambda: Reviewer(),
    )
    result = await independent_reviewer_service.review_task(
        {"id": "task_1", "run_id": "run_1", "task_type": "experiment_design"},
        {"claims": [], "reproducible_experiment": {"publishable": True}}, {"excerpts": []},
    )
    assert result["approved"] is True
    assert result["reviewer"] == "independent_reviewer_model_minimal"
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_independent_reviewer_uses_deliverable_scope_for_system_design(monkeypatch):
    prompts = []

    class Reviewer:
        async def generate(self, prompt, **_kwargs):
            prompts.append(prompt)
            return '{"approved":true,"issues":[],"summary":"design is internally consistent"}'

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.create_llm_provider",
        lambda: Reviewer(),
    )
    result = await independent_reviewer_service.review_task(
        {"id": "task_1", "run_id": "run_1", "task_type": "system_design", "description": "freeze parameters"},
        {"claims": [], "summary": "parameters frozen", "findings": ["seed=42"]},
        {"excerpts": []},
    )
    assert result["approved"] is True
    assert '"deliverable"' in prompts[0]
    assert "不得仅因没有 passage 或 experiment artifact 判为不通过" in prompts[0]


@pytest.mark.asyncio
async def test_chapter_reviewer_receives_full_chapter_and_frozen_support(monkeypatch):
    prompts = []

    class Reviewer:
        async def generate(self, prompt, **_kwargs):
            prompts.append(prompt)
            return '{"approved":true,"issues":[],"summary":"chapter is grounded"}'

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.create_llm_provider",
        lambda: Reviewer(),
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.ResearchClaimRepository.get_by_run",
        lambda _run_id: [{
            "id": "claim_verified", "statement": "bounded pilot result",
            "status": "supported", "evidence_ids": ["artifact_1"],
        }],
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.ResearchBriefRepository.get_by_run",
        lambda _run_id: {
            "research_question": "frozen question", "objective": "frozen objective",
            "scope_in": ["pilot"], "scope_out": ["open domain"],
            "methodology_profile": {"family": "controlled_experiment"},
        },
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.thesis_chapter_service.artifact_support",
        lambda _run_id: [{
            "id": "experiment:verified", "rows": [{"strategy": "overlap", "mrr_at_10": 1.0}],
        }],
    )
    result = await independent_reviewer_service.review_task(
        {"id": "chapter_1", "run_id": "run_1", "task_type": "thesis_chapter"},
        {
            "summary": "chapter", "claims": [{"statement": "duplicate writing claim"}],
            "chapter": {"name": "Introduction", "sections": [{
                "heading": "Scope", "paragraphs": [{
                    "text": "complete chapter body", "support_ids": ["claim_verified"],
                }],
            }]},
        },
        {"excerpts": []},
    )

    assert result["approved"] is True
    assert result["reviewer"] == "independent_reviewer_model_paragraph_audit_v3_global"
    assert "引言可以简要预览关键数值" in prompts[-1]
    assert len(prompts) == 2
    assert "逐段穷尽检查" in prompts[0]
    assert "interpretation/limitation" in prompts[0]
    assert "不得要求来源逐字写出作者自己的综合判断" in prompts[0]
    assert "complete chapter body" in prompts[0]
    assert "bounded pilot result" in prompts[0]
    assert '"available_support"' in prompts[0]
    assert '"chapter"' in prompts[-1]
    assert '"allowed_support"' in prompts[-1]
    assert '"allowed_contract_support"' in prompts[-1]
    assert '"allowed_artifact_support"' in prompts[-1]
    assert "experiment:verified" in prompts[-1]
    assert "frozen question" in prompts[-1]
    assert "bounded pilot result" in prompts[-1]
    assert "不得声称章节正文或原始依据未提供" in prompts[-1]
    assert "不得把 brief:* ID 判为无效" in prompts[-1]
    assert "工件中没有的" in prompts[-1]
    assert "paragraph_support_audit" in prompts[-1]
    assert prompts[-1].index('"allowed_artifact_support"') < prompts[-1].index('"deliverable"')


@pytest.mark.asyncio
async def test_chapter_reviewer_collects_all_bounded_batch_support_issues(monkeypatch):
    prompts = []

    class Reviewer:
        async def generate(self, prompt, **_kwargs):
            prompts.append(prompt)
            target = "p0" if '"id":"p0"' in prompt else "p6"
            return json.dumps({
                "approved": False,
                "issues": [{
                    "severity": "major", "target": target,
                    "reason": f"{target} contains an unsupported mechanism",
                    "required_change": f"delete the unsupported phrase in {target}",
                }],
                "summary": "support mismatch",
            })

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.create_llm_provider",
        lambda: Reviewer(),
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.ResearchClaimRepository.get_by_run",
        lambda _run_id: [{
            "id": "claim_verified", "statement": "bounded result",
            "status": "supported", "evidence_ids": ["source"],
        }],
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.ResearchBriefRepository.get_by_run",
        lambda _run_id: {},
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.thesis_chapter_service.artifact_support",
        lambda _run_id: [],
    )

    result = await independent_reviewer_service.review_task(
        {"id": "chapter", "run_id": "run", "task_type": "thesis_chapter"},
        {"chapter": {"sections": [{"paragraphs": [
            {
                "id": f"p{index}", "text": f"paragraph {index} factual mechanism",
                "paragraph_type": "claim", "support_ids": ["claim_verified"],
            }
            for index in range(7)
        ]}]}},
        {"excerpts": []},
    )

    assert result["approved"] is False
    assert result["reviewer"] == "independent_reviewer_model_paragraph_audit_v2"
    assert [item["target"] for item in result["issues"]] == ["p0", "p6"]
    assert len(prompts) == 2


@pytest.mark.asyncio
async def test_chapter_support_audit_uses_chapter_token_budget_without_binary_fallback(monkeypatch):
    calls = []

    class EmptyReviewer:
        async def generate(self, schema, max_tokens=None, **_kwargs):
            calls.append((schema, max_tokens))
            return ""

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(settings, "llm_structured_repair_attempts", 1)
    monkeypatch.setattr(settings, "thesis_chapter_max_tokens", 8192)
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.create_llm_provider",
        lambda: EmptyReviewer(),
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.ResearchClaimRepository.get_by_run",
        lambda _run_id: [{
            "id": "claim_verified", "statement": "bounded result",
            "status": "supported", "evidence_ids": ["source"],
        }],
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.ResearchBriefRepository.get_by_run",
        lambda _run_id: {},
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.thesis_chapter_service.artifact_support",
        lambda _run_id: [],
    )

    result = await independent_reviewer_service.review_task(
        {"id": "chapter", "run_id": "run", "task_type": "thesis_chapter"},
        {"chapter": {"sections": [{"paragraphs": [{
            "id": "p0", "text": "bounded factual paragraph",
            "paragraph_type": "claim", "support_ids": ["claim_verified"],
        }]}]}},
        {"excerpts": []},
    )

    assert result["approved"] is False
    assert result["issues"][0]["target"] == "review_transport"
    assert len(calls) == 2
    assert all(schema == independent_reviewer_service.SCHEMA for schema, _ in calls)
    assert all(max_tokens == 8192 for _, max_tokens in calls)


@pytest.mark.asyncio
async def test_thesis_reviewer_drops_false_unknown_issue_for_schema_verified_support(monkeypatch):
    class Reviewer:
        async def generate(self, **_kwargs):
            return json.dumps({
                "approved": False,
                "issues": [{
                    "severity": "major",
                    "target": "claim_verified 无效",
                    "reason": "claim_verified 未在 allowed_support 中出现",
                    "required_change": "替换该无效 support ID",
                }],
                "summary": "support ID missing",
            })

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.create_llm_provider",
        lambda: Reviewer(),
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.ResearchClaimRepository.get_by_run",
        lambda _run_id: [{
            "id": "claim_verified", "statement": "frozen fact",
            "status": "supported", "evidence_ids": ["source"],
        }],
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.ResearchBriefRepository.get_by_run",
        lambda _run_id: {},
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.thesis_chapter_service.artifact_support",
        lambda _run_id: [],
    )

    result = await independent_reviewer_service.review_task(
        {"id": "chapter", "run_id": "run", "task_type": "thesis_chapter"},
        {"chapter": {"sections": [{"paragraphs": [{"support_ids": ["claim_verified"]}]}]}},
        {"excerpts": []},
    )

    assert result["approved"] is True
    assert result["issues"] == []


@pytest.mark.asyncio
async def test_independent_reviewer_respects_frozen_evaluation_only_experiment(monkeypatch):
    prompts = []

    class Reviewer:
        async def generate(self, prompt, **_kwargs):
            prompts.append(prompt)
            return '{"approved":true,"issues":[],"summary":"bounded pilot is adequately preregistered"}'

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.create_llm_provider",
        lambda: Reviewer(),
    )
    result = await independent_reviewer_service.review_task(
        {"id": "task_exp", "run_id": "run_1", "task_type": "experiment_design"},
        {"claims": [], "reproducible_experiment": {
            "preregistration_path": "/tmp/preregistration.md",
            "protocol": {"method_details": {
                "evaluation_design": {"data_split": "no fitting; frozen evaluation-only benchmark"},
                "scope": "controlled pilot only",
            }},
        }},
        {"excerpts": []},
    )
    assert result["approved"] is True
    assert "不得机械要求训练/测试划分" in prompts[0]
    assert "不得仅因样本小而要求擅自扩大" in prompts[0]


@pytest.mark.asyncio
async def test_result_analysis_reviewer_sees_deliverable_and_cannot_rewrite_experiment(monkeypatch):
    prompts = []

    class Reviewer:
        async def generate(self, prompt, **_kwargs):
            prompts.append(prompt)
            return '{"approved":true,"issues":[],"summary":"bounded interpretation is sufficient"}'

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.create_llm_provider",
        lambda: Reviewer(),
    )
    result = await independent_reviewer_service.review_task(
        {"id": "task_analysis", "run_id": "run_1", "task_type": "result_analysis"},
        {
            "claims": [{"statement": "均匀效应可能源于同构构造，仅限冻结 pilot。"}],
            "analysis_artifact": {"limitations": ["禁止外推"]},
            "reproducible_experiment": {
                "metrics": {"benchmark_design": {"kind": "controlled pilot"}},
            },
        },
        {"excerpts": []},
    )
    assert result["approved"] is True
    assert '"deliverable"' in prompts[0]
    assert "不可由分析任务改写" in prompts[0]
    assert "不能要求改写上游实验工件" in prompts[0]


@pytest.mark.asyncio
async def test_quantitative_result_reviewer_sees_method_provenance_without_experiment_fields(monkeypatch):
    prompts = []

    class Reviewer:
        async def generate(self, prompt, **_kwargs):
            prompts.append(prompt)
            return '{"approved":true,"issues":[],"summary":"method artifact is traceable"}'

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.create_llm_provider",
        lambda: Reviewer(),
    )
    provenance = {
        "method_family": "quantitative", "input_hashes": ["a" * 64],
        "analysis_artifact": "analysis/result.json", "analysis_artifact_sha256": "b" * 64,
    }
    result = await independent_reviewer_service.review_task(
        {"id": "task_analysis", "run_id": "run_without_brief", "task_type": "result_analysis"},
        {
            "claims": [{"statement": "bounded descriptive difference", "provenance": provenance}],
            "analysis_artifact": {
                "family": "quantitative", "input_hashes": ["a" * 64],
                "findings": [{"records_total": 4, "mean_difference": 2.0}],
                "limitations": ["descriptive only"],
            },
        },
        {"excerpts": []},
    )

    assert result["approved"] is True
    assert '"provenance"' in prompts[0]
    assert '"analysis_artifact_sha256"' in prompts[0]
    assert "不是实验复现" in prompts[0]


def test_independent_reviewer_normalizes_harmless_field_drift():
    value = independent_reviewer_service._compact_review({
        "approved": False,
        "issues": {"severity": "high", "area": "statistics", "description": "CI is missing", "recommendation": "add CI"},
        "conclusion": "revision required",
    })
    assert value == {
        "approved": False,
        "issues": [{
            "severity": "major", "target": "statistics", "reason": "CI is missing",
            "required_change": "add CI",
        }],
        "summary": "revision required",
    }


def test_independent_reviewer_keeps_twelve_exhaustive_batch_issues():
    issues = [
        {
            "severity": "major", "target": f"p{index}",
            "reason": f"unsupported {index}", "required_change": "delete",
        }
        for index in range(12)
    ]

    value = independent_reviewer_service._compact_review({
        "approved": False, "issues": issues, "summary": "batch audit",
    })

    assert len(value["issues"]) == 12
    assert value["issues"][-1]["target"] == "p11"


def test_chapter_batch_issue_is_anchored_to_quoted_paragraph():
    review = {
        "approved": False,
        "issues": [{
            "severity": "major", "target": "overall",
            "reason": "The phrase is not supported",
            "required_change": "Delete 'dense embeddings capture semantic similarity'",
        }],
        "summary": "unsupported phrase",
    }
    batch = [
        {"id": "intro_1", "text": "This paragraph discusses scope."},
        {"id": "intro_2", "text": "Dense embeddings capture semantic similarity beyond exact matches."},
    ]

    anchored = independent_reviewer_service._anchor_batch_issue_targets(review, batch)

    assert anchored["issues"][0]["target"] == "intro_2"


def test_chapter_batch_unlocated_deletion_is_review_transport_failure():
    review = {
        "approved": False,
        "issues": [{
            "severity": "major", "target": "intro_2", "reason": "",
            "required_change": "Delete the unsupported phrase. No available support can be bound to justify it.",
        }],
        "summary": "unsupported phrase",
    }
    batch = [
        {"id": "intro_1", "text": "This paragraph discusses scope."},
        {"id": "intro_2", "text": "This paragraph makes several bounded observations."},
    ]

    anchored = independent_reviewer_service._anchor_batch_issue_targets(review, batch)

    assert anchored["issues"] == [{
        "severity": "major",
        "target": "review_transport",
        "reason": "independent reviewer requested deletion without identifying the unsupported text",
        "required_change": "retry paragraph audit and quote the minimum exact phrase",
    }]


def test_large_artifact_support_is_compacted_to_relevant_frozen_facts():
    support = {
        "id": "experiment:verified",
        "protocol": {"method_details": {
            "strategies": {"fixed_overlap": {"chunk_size": 100, "overlap": 30}},
            "window_size": "100 characters", "overlap": "30 characters",
        }},
        "rows": [{"strategy": "fixed overlap", "mrr_at_10": 1.0}],
        "noise": [{f"unused_{index}": "unrelated material " * 30} for index in range(80)],
    }

    view = independent_reviewer_service._audit_support_view(
        support,
        [{"text": "The fixed overlap strategy uses a 100 character window and 30 character overlap."}],
    )

    rendered = json.dumps(view, ensure_ascii=False)
    assert view["id"] == "experiment:verified"
    assert view["compacted_for_paragraph_audit"] is True
    assert view["frozen_method_contract"]["strategies"]["fixed_overlap"]["chunk_size"] == 100
    assert "window_size" in rendered
    assert "100 characters" in rendered
    assert "overlap" in rendered
    assert len(rendered) < 9000


def test_literature_reviewer_must_not_invent_missing_source_statistics():
    scope = independent_reviewer_service._literature_review_scope()
    assert "不是复现被引论文" in scope
    assert "不得要求作者替被引论文补做" in scope
    assert "正确处理是把缺失项列为来源局限" in scope
    assert "定性 passage 不机械要求效果量" in scope


def test_research_design_reviewer_checks_plan_not_future_results():
    scope = independent_reviewer_service._research_design_review_scope()
    assert "尚未执行的前瞻性研究设计" in scope
    assert "不得要求 experiment" in scope
    assert "不得诱导模型编造" in scope
    assert "质量控制" in scope
    assert "材料登记/分析阶段" in scope


@pytest.mark.asyncio
async def test_research_design_review_payload_omits_experiment_and_passages(monkeypatch):
    prompts = []

    class Reviewer:
        async def generate(self, prompt, **_kwargs):
            prompts.append(prompt)
            return '{"approved":true,"issues":[],"summary":"prospective design is complete"}'

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.create_llm_provider",
        lambda: Reviewer(),
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.ResearchBriefRepository.get_by_run",
        lambda _run_id: {
            "methodology_family": "quantitative",
            "methodology_profile": {"family": "quantitative", "epistemic_mode": "observational"},
        },
    )
    result = await independent_reviewer_service.review_task(
        {"id": "design", "run_id": "run", "task_type": "research_design", "description": "long"},
        {
            "method_package": {
                "family": "quantitative", "study_design": "cross-sectional",
                "quality_controls": ["complete-case disclosure", "non-causal language"],
            },
            "claims": [{"statement": "unverified external method claim"}],
        },
        {"excerpts": []},
    )

    assert result["approved"] is True
    assert '"deliverable"' in prompts[0]
    assert '"experiment"' not in prompts[0]
    assert '"passages"' not in prompts[0]
    assert "不得要求 experiment" in prompts[0]


def test_data_acquisition_reviewer_understands_manifest_semantics():
    scope = independent_reviewer_service._data_acquisition_review_scope()
    assert "不表示数据文件内部每个统计字段都无缺失" in scope
    assert "相对归档路径 relative_path" in scope
    assert "不得机械要求网页截图" in scope
    assert "required=false" in scope
    assert "LLM 不得改写文件哈希" in scope


@pytest.mark.asyncio
async def test_data_acquisition_review_payload_omits_experiment_and_passages(monkeypatch):
    prompts = []

    class Reviewer:
        async def generate(self, prompt, **_kwargs):
            prompts.append(prompt)
            return '{"approved":true,"issues":[],"summary":"manifest is auditable"}'

    monkeypatch.setattr(settings, "mock_mode", False)
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.create_llm_provider",
        lambda: Reviewer(),
    )
    monkeypatch.setattr(
        "backend.app.services.independent_reviewer_service.ResearchBriefRepository.get_by_run",
        lambda _run_id: {"ethics_plan": {"required": False, "status": "not_required"}},
    )
    result = await independent_reviewer_service.review_task(
        {"id": "materials", "run_id": "run", "task_type": "data_acquisition"},
        {
            "material_manifest": {
                "completeness": "complete",
                "ethics_exemption_reason": "No participant recruitment.",
                "source_records": [{"id": "m1", "sha256": "a" * 64}],
            },
            "claims": [{"statement": "must not enter the manifest review"}],
        },
        {"excerpts": [{"id": "p1", "excerpt": "must not enter the manifest review"}]},
    )

    assert result["approved"] is True
    assert '"material_manifest"' in prompts[0]
    assert '"experiment"' not in prompts[0]
    assert '"passages"' not in prompts[0]
    assert "不得机械要求网页截图" in prompts[0]


def test_reviewer_payload_compaction_keeps_complete_json_and_claims():
    payload = {
        "task": {"id": "task", "description": "x" * 20000},
        "claims": [
            {
                "index": index,
                "statement": f"claim {index}",
                "passages": [{"passage_id": f"p{index}", "text": "evidence " * 2000}],
            }
            for index in range(6)
        ],
    }

    compact = independent_reviewer_service._compact_payload_json(payload, 24000)
    parsed = json.loads(compact)

    assert len(parsed["claims"]) == 6
    assert all(claim["passages"][0]["passage_id"] for claim in parsed["claims"])
    assert not compact.rstrip().endswith((":", ","))


@pytest.mark.asyncio
async def test_partial_entailment_is_audited_but_not_kept_as_claim(monkeypatch):
    async def partial(*_args):
        return [{
            "claim_index": 0, "verdict": "partially_entailed",
            "passage_ids": ["p1"], "rationale": "except X does not imply X increased",
        }]

    monkeypatch.setattr(claim_entailment_service, "_ask_model", partial)
    monkeypatch.setattr(settings, "mock_mode", False)
    result = await claim_entailment_service.verify(
        {"claims": [{
            "statement": "All groups declined except X, where it increased.",
            "evidence_passage_ids": ["p1"],
        }]},
        [{"id": "p1", "excerpt": "All groups declined except X."}],
        "run", "task",
    )

    assert result["claims"] == []
    assert result["entailment_audit"]["rejected"] == 1
    assert result["entailment_audit"]["rejected_claims"][0]["verdict"] == "partially_entailed"


def test_review_transport_failure_stops_without_full_task_revision(monkeypatch):
    monkeypatch.setattr(review_service, "_persist_review", lambda *_args: None)
    gates = {
        "passed": False,
        "layers": {
            "schema": {"passed": True, "issues": []},
            "provenance": {"passed": True, "issues": []},
            "semantic": {"passed": True, "issues": []},
            "method": {"passed": True, "issues": []},
            "independent_review": {
                "passed": False,
                "issues": [{"target": "review_transport", "reason": "invalid JSON"}],
            },
        },
        "revision_plan": [],
    }
    review = review_service._review_quality_gate_failure(
        {"id": "task_1", "task_type": "experiment_design"}, gates,
    )
    assert review["requires_revision"] is False
    assert review["review_mode"] == "independent_review_transport_failure"
