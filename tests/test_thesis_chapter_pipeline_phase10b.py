import uuid
import json
from datetime import datetime

import pytest

from backend.app.services.report_service import ReportService
from backend.app.services.review_service import ReviewService
from backend.app.services.task_executor import TaskExecutor
from backend.app.services.research_state_service import research_state_service
from backend.app.services.run_execution_service import run_execution_service
from backend.app.services.task_recovery_service import task_recovery_service
from backend.app.services.thesis_chapter_service import thesis_chapter_service
from backend.app.storage import init_db
from backend.app.storage.repositories import (
    EvidenceRepository, ExperimentProtocolRepository, ExperimentResultRepository,
    ResearchBriefRepository, ResearchClaimRepository,
    RunRepository, TaskDependencyRepository, TaskRepository,
)


@pytest.fixture(autouse=True)
def _db():
    init_db()


def _insert_task(run_id: str, task_id: str, task_type: str, status: str = "completed") -> dict:
    now = datetime.now().isoformat()
    task = {
        "id": task_id, "run_id": run_id, "title": task_id, "description": "",
        "task_type": task_type, "required_skills": {}, "status": status,
        "created_at": now, "updated_at": now,
    }
    TaskRepository.insert(task)
    return task


def test_chapter_parser_discards_nonauthoritative_top_level_claim_shape():
    raw = json.dumps({
        "summary": "chapter draft",
        "claims": {"statement": "must not become a new graph claim"},
        "chapter": {"sections": []},
    })

    parsed = TaskExecutor._parse_result(raw, reset_claims=True)

    assert parsed["claims"] == []
    with pytest.raises(ValueError, match="claims must be an array"):
        TaskExecutor._parse_result(raw)


def _run_with_thesis(tmp_path, chapters=None, citation_style="Chicago") -> tuple[str, dict]:
    now = datetime.now().isoformat()
    run_id = f"run_chapters_{uuid.uuid4().hex[:8]}"
    run = {
        "id": run_id, "research_goal": "完成跨学科硕士论文", "artifact_dir": str(tmp_path / run_id),
        "status": "created", "created_at": now, "updated_at": now,
    }
    RunRepository.insert(run)
    research_state_service.ensure_initialized(run)
    ResearchBriefRepository.update(
        run_id,
        research_question="冻结研究问题如何由真实材料得到回答？",
        objective="完成可追溯硕士论文",
        expected_contribution="形成由真实材料支持的跨学科论证",
        data_availability="材料随工件清单提供",
        discipline={"broad_field": "humanities", "field": "history", "subfield": "intellectual_history"},
        methodology_family="humanities",
        methodology_profile={"family": "humanities", "epistemic_mode": "interpretation"},
        ethics_plan={"required": False, "status": "not_required"},
        thesis_requirements={
            "status": "confirmed", "degree_level": "master", "institution": "测试大学",
            "programme": "历史学", "language": "zh-CN", "citation_style": citation_style,
            "target_word_count": 3000, "minimum_references": 5, "minimum_supported_claims": 1,
            "required_chapters": chapters or ["引言", "方法", "分析", "结论"],
        },
    )
    return run_id, run


def _chapter_output(name: str, budget: int, claim_id: str) -> dict:
    paragraph = "本段严格依据已经通过审核的研究结论展开解释，并区分材料事实、作者推论、反论证和适用边界。" * 20
    return {
        "summary": f"完成{name}", "claims": [],
        "chapter": {
            "name": name, "word_budget": budget,
            "sections": [{
                "heading": f"{name}核心论证",
                "paragraphs": [
                    {"id": f"{name}_p1", "text": paragraph, "paragraph_type": "claim", "support_ids": [claim_id]},
                    {"id": f"{name}_p2", "text": paragraph, "paragraph_type": "interpretation", "support_ids": [claim_id]},
                    {"id": f"{name}_p3", "text": paragraph, "paragraph_type": "limitation", "support_ids": []},
                ],
            }],
        },
    }


def test_chapter_plan_allocates_declared_total_across_required_chapters():
    plan = thesis_chapter_service.chapter_plan({
        "target_word_count": 30000,
        "required_chapters": ["引言", "文献综述", "方法", "结果", "讨论", "结论"],
    })
    assert len(plan) == 6
    assert sum(item["word_budget"] for item in plan) == pytest.approx(30000, abs=3)
    assert next(item for item in plan if item["chapter_name"] == "文献综述")["word_budget"] > next(
        item for item in plan if item["chapter_name"] == "结论"
    )["word_budget"]


def test_chapter_tasks_are_created_once_and_depend_on_completed_research(tmp_path):
    run_id, _ = _run_with_thesis(tmp_path)
    research = _insert_task(run_id, f"research_{uuid.uuid4().hex[:8]}", "result_analysis")
    archived = _insert_task(run_id, f"archived_{uuid.uuid4().hex[:8]}", "research_design", "archived")
    report = _insert_task(run_id, f"report_{uuid.uuid4().hex[:8]}", "report_writing", "pending")

    created = thesis_chapter_service.ensure_tasks(run_id)
    TaskDependencyRepository.replace_for_task(created[0]["id"], [archived["id"]])
    repeated = thesis_chapter_service.ensure_tasks(run_id)

    assert len(created) == len(repeated) == 4
    assert {item["id"] for item in created} == {item["id"] for item in repeated}
    assert all(TaskDependencyRepository.get_for_task(item["id"]) == [research["id"]] for item in created)
    assert set(TaskDependencyRepository.get_for_task(report["id"])) == {item["id"] for item in created}


def test_transient_chapter_json_failure_gets_one_bounded_retry(tmp_path, monkeypatch):
    run_id, _ = _run_with_thesis(tmp_path)
    task = _insert_task(run_id, f"chapter_{uuid.uuid4().hex[:8]}", "thesis_chapter", "failed")
    TaskRepository.update_status(
        task["id"], "failed", attempt_count=1,
        blocked_reason="LLM structured output invalid after 2 attempt(s): response is not valid JSON",
    )
    task = TaskRepository.get_by_id(task["id"])
    retried = []
    monkeypatch.setattr(task_recovery_service, "retry", lambda item, reason: retried.append((item["id"], reason)))

    assert run_execution_service._retry_transient_writing_failures([task]) is True
    assert retried and retried[0][0] == task["id"]

    task["attempt_count"] = 2
    assert run_execution_service._retry_transient_writing_failures([task]) is False


@pytest.mark.asyncio
async def test_chapter_generation_uses_longform_token_budget():
    calls = []

    class FakeLLM:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            return '{"summary":"ok","claims":[]}'

    await TaskExecutor()._generate_structured(
        FakeLLM(), "prompt", {"task_type": "thesis_chapter"}, "writer",
    )
    assert calls[0]["max_tokens"] == 8192

    calls.clear()
    await TaskExecutor()._generate_structured(
        FakeLLM(), "prompt", {"task_type": "literature_survey"}, "researcher",
    )
    assert calls[0]["max_tokens"] is None

    calls.clear()
    await TaskExecutor()._generate_structured(
        FakeLLM(), "prompt", {"task_type": "result_analysis"}, "analyst",
    )
    assert calls[0]["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_short_chapter_gets_bounded_monotonic_expansion(monkeypatch):
    calls = []
    expanded = {
        "summary": "expanded", "claims": [],
        "chapter": {"sections": [{"paragraphs": [{"text": "expanded text"}]}]},
    }

    class FakeLLM:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            return json.dumps(expanded)

    task = {
        "id": "chapter", "task_type": "thesis_chapter",
        "description": '【thesis_chapter_spec】{"chapter_name":"Results","word_budget":1000}\n',
    }
    counts = iter([400, 780])
    monkeypatch.setattr(thesis_chapter_service, "minimum_word_count", lambda _task: 500)
    monkeypatch.setattr(thesis_chapter_service, "word_count", lambda *_args: next(counts))
    monkeypatch.setattr(thesis_chapter_service, "validate_output", lambda *_args: [])
    result = await TaskExecutor()._expand_short_chapter(
        FakeLLM(), "original prompt", task, "writer",
        {"summary": "short", "claims": [{"statement": "keep"}], "chapter": {"sections": []}},
    )

    assert result["chapter"] == expanded["chapter"]
    assert result["summary"] == "short"
    assert result["claims"] == [{"statement": "keep"}]
    assert len(calls) == 1
    assert "硬性最低 500 词" in calls[0]["prompt"]
    assert "不得补充机制、因果、效果解释或领域常识" in calls[0]["prompt"]
    assert "original prompt" not in calls[0]["prompt"]
    assert calls[0]["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_chapter_expansion_rejects_shorter_draft_then_stops_after_second_round(monkeypatch):
    calls = []

    class FakeLLM:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            marker = "shorter" if len(calls) == 1 else "longer"
            return json.dumps({
                "summary": "expanded", "claims": [],
                "chapter": {"marker": marker, "sections": []},
            })

    task = {
        "id": "chapter", "task_type": "thesis_chapter",
        "description": '【thesis_chapter_spec】{"chapter_name":"Results","word_budget":1000}\n',
    }
    monkeypatch.setattr(
        thesis_chapter_service,
        "word_count",
        lambda _task, output: {None: 400, "shorter": 350, "longer": 780}[
            (output.get("chapter") or {}).get("marker")
        ],
    )
    monkeypatch.setattr(thesis_chapter_service, "minimum_word_count", lambda _task: 500)
    monkeypatch.setattr(thesis_chapter_service, "validate_output", lambda *_args: [])

    result = await TaskExecutor()._expand_short_chapter(
        FakeLLM(), "unused", task, "writer",
        {"summary": "original", "claims": [], "chapter": {"sections": []}},
    )

    assert len(calls) == 2
    assert result["chapter"]["marker"] == "longer"


@pytest.mark.asyncio
async def test_chapter_expansion_uses_distributed_length_target(monkeypatch):
    calls = []

    class FakeLLM:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            return json.dumps({
                "summary": "expanded", "claims": [],
                "chapter": {"marker": "expanded", "sections": []},
            })

    task = {
        "id": "chapter", "task_type": "thesis_chapter",
        "description": (
            '【thesis_chapter_spec】{"chapter_name":"Results","word_budget":2000}\n'
            "将正文控制在 1900–1960 词。"
        ),
    }
    counts = iter([800, 1920])
    monkeypatch.setattr(thesis_chapter_service, "minimum_word_count", lambda _task: 600)
    monkeypatch.setattr(thesis_chapter_service, "word_count", lambda *_args: next(counts))
    monkeypatch.setattr(thesis_chapter_service, "validate_output", lambda *_args: [])

    await TaskExecutor()._expand_short_chapter(
        FakeLLM(), "unused", task, "writer",
        {"summary": "short", "claims": [], "chapter": {"sections": []}},
    )

    assert len(calls) == 1
    assert "硬性最低 1900 词" in calls[0]["prompt"]


def test_chapter_gate_requires_supported_ids_and_substantive_budget(tmp_path):
    run_id, _ = _run_with_thesis(tmp_path, ["分析"])
    claim_id = f"claim_supported_{uuid.uuid4().hex[:8]}"
    ResearchClaimRepository.insert({
        "id": claim_id, "run_id": run_id, "statement": "冻结史料支持限定解释",
        "status": "supported", "evidence_ids": ["artifact"], "confidence": 0.9,
        "created_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat(),
    })
    task = thesis_chapter_service.ensure_tasks(run_id)[0]
    spec = thesis_chapter_service.spec_from_task(task)
    valid = _chapter_output("分析", spec["word_budget"], claim_id)
    assert thesis_chapter_service.validate_output(task, valid) == []

    invalid = _chapter_output("分析", spec["word_budget"], "invented_claim")
    invalid["chapter"]["sections"][0]["paragraphs"] = invalid["chapter"]["sections"][0]["paragraphs"][:1]
    issues = thesis_chapter_service.validate_output(task, invalid)
    assert any("unknown_support:invented_claim" in issue for issue in issues)
    assert "chapter_paragraph_count_insufficient" in issues


def test_chapter_minimum_is_structural_while_institutional_floor_stays_at_full_thesis(tmp_path):
    run_id, _ = _run_with_thesis(tmp_path, ["Analysis"])
    brief = ResearchBriefRepository.get_by_run(run_id)
    requirements = dict(brief["thesis_requirements"])
    requirements.update({"target_word_count": 3000, "minimum_word_count": 2800})
    ResearchBriefRepository.update(run_id, thesis_requirements=requirements)
    task = thesis_chapter_service.ensure_tasks(run_id)[0]

    assert thesis_chapter_service.minimum_word_count(task) == 900
    assert (ResearchBriefRepository.get_by_run(run_id)["thesis_requirements"])["minimum_word_count"] == 2800


def test_total_length_adjustment_targets_largest_excess_chapter(monkeypatch):
    chapters = [
        {"id": "intro", "status": "completed", "description": '【thesis_chapter_spec】{"word_budget":1000}\n', "outputs": [{"count": 1100}]},
        {"id": "results", "status": "completed", "description": '【thesis_chapter_spec】{"word_budget":1200}\n', "outputs": [{"count": 1700}]},
    ]
    monkeypatch.setattr(ResearchBriefRepository, "get_by_run", lambda _run_id: {
        "thesis_requirements": {"minimum_word_count": 2000, "maximum_word_count": 2500},
    })
    monkeypatch.setattr(thesis_chapter_service, "resolved_chapters", lambda _run_id: chapters)
    monkeypatch.setattr(thesis_chapter_service, "word_count", lambda task, _output: task["outputs"][-1]["count"])
    monkeypatch.setattr(thesis_chapter_service, "minimum_word_count", lambda _task: 900)

    adjustment = thesis_chapter_service.total_word_adjustment("run_length")

    assert adjustment["task"]["id"] == "results"
    assert adjustment["direction"] == "condense"
    assert adjustment["target"] == 1340


def test_total_length_expansion_is_distributed_by_chapter_budget(monkeypatch):
    chapters = [
        {"id": "intro", "status": "completed", "description": '【thesis_chapter_spec】{"word_budget":1000}\n', "outputs": [{"count": 500}]},
        {"id": "results", "status": "completed", "description": '【thesis_chapter_spec】{"word_budget":1200}\n', "outputs": [{"count": 600}]},
    ]
    monkeypatch.setattr(ResearchBriefRepository, "get_by_run", lambda _run_id: {
        "thesis_requirements": {
            "minimum_word_count": 2000, "target_word_count": 2200,
            "maximum_word_count": 2400,
        },
    })
    monkeypatch.setattr(thesis_chapter_service, "resolved_chapters", lambda _run_id: chapters)
    monkeypatch.setattr(
        thesis_chapter_service, "word_count",
        lambda task, _output: task["outputs"][-1]["count"],
    )

    adjustments = thesis_chapter_service.total_word_adjustments("run_length")

    assert [(item["task"]["id"], item["target"]) for item in adjustments] == [
        ("intro", 1000), ("results", 1200),
    ]


def test_chapter_gate_accepts_frozen_experiment_support(tmp_path, monkeypatch):
    run_id, _ = _run_with_thesis(tmp_path, ["Results"])
    task = thesis_chapter_service.ensure_tasks(run_id)[0]
    monkeypatch.setattr(
        thesis_chapter_service, "artifact_support",
        lambda _run_id: [{"id": "experiment:verified_result", "rows": [{"mrr_at_10": 1.0}]}],
    )
    output = _chapter_output(
        "Results", thesis_chapter_service.spec_from_task(task)["word_budget"],
        "experiment:verified_result",
    )

    assert thesis_chapter_service.validate_output(task, output) == []


def test_surgical_chapter_repair_only_deletes_original_sentences_and_binds_verified_ids(monkeypatch):
    monkeypatch.setattr(ResearchClaimRepository, "get_by_run", lambda _run_id: [])
    monkeypatch.setattr(
        thesis_chapter_service, "artifact_support",
        lambda _run_id: [{"id": "experiment:verified"}],
    )
    original = (
        "The frozen pilot compares three strategies. "
        "Overlapping chunks eliminate every boundary failure. "
        "The conclusion remains limited to the frozen benchmark."
    )
    latest = {
        "summary": "chapter", "claims": [],
        "chapter": {"sections": [{"heading": "Scope", "paragraphs": [{
            "id": "p1", "text": original, "paragraph_type": "claim",
            "support_ids": ["brief:scope"],
        }]}]},
    }
    review = {"quality_gates": {"layers": {"independent_review": {"issues": [
        {
            "target": "p1",
            "reason": "'Overlapping chunks eliminate every boundary failure.' is not supported",
            "required_change": "delete the unsupported sentence",
        },
        {
            "target": "p1", "reason": "The pilot setup is available in experiment:verified",
            "required_change": "bind 'experiment:verified'",
        },
    ]}}}}

    repaired = thesis_chapter_service.surgical_repair(
        {"run_id": "run"}, latest, review,
    )
    paragraph = repaired["result"]["chapter"]["sections"][0]["paragraphs"][0]

    assert paragraph["text"] == (
        "The frozen pilot compares three strategies. "
        "The conclusion remains limited to the frozen benchmark."
    )
    assert paragraph["support_ids"] == ["brief:scope", "experiment:verified"]
    assert [item["operation"] for item in repaired["changes"]] == ["delete", "bind"]
    assert repaired["unresolved"] == []


def test_surgical_chapter_repair_prefers_exact_phrases_over_deleting_supported_sentence(monkeypatch):
    monkeypatch.setattr(ResearchClaimRepository, "get_by_run", lambda _run_id: [])
    monkeypatch.setattr(thesis_chapter_service, "artifact_support", lambda _run_id: [])
    original = (
        "DPR improves retrieval accuracy on the frozen benchmark, "
        "establishing DPR as a universal baseline for every domain."
    )
    latest = {"chapter": {"sections": [{"paragraphs": [{
        "id": "p1", "text": original, "support_ids": ["brief:scope"],
    }]}]}}
    review = {"quality_gates": {"layers": {"independent_review": {"issues": [{
        "target": "p1", "reason": "'establishing DPR as a universal baseline for every domain' is unsupported",
        "required_change": "delete the unsupported phrase",
    }]}}}}

    repaired = thesis_chapter_service.surgical_repair({"run_id": "run"}, latest, review)
    text = repaired["result"]["chapter"]["sections"][0]["paragraphs"][0]["text"]

    assert text == "DPR improves retrieval accuracy on the frozen benchmark."
    assert "DPR improves retrieval accuracy" in text


def test_malformed_cleanup_preserves_citation_sentences_and_drops_orphans():
    text = (
        "Karpukhin et al. (2020) reported a bounded result. "
        "The thesis. Work by Zhou et al. (2026) and Smith et al. "
        "The supported conclusion remains bounded."
    )

    cleaned = thesis_chapter_service._drop_malformed_sentences(text)

    assert "Karpukhin et al. (2020) reported a bounded result." in cleaned
    assert "The supported conclusion remains bounded." in cleaned
    assert "The thesis." not in cleaned
    assert "Work by Zhou" not in cleaned


def test_advisor_named_paragraphs_restore_exactly_from_persisted_previous_chapter():
    previous = {
        "chapter": {"sections": [{"heading": "Related Work", "paragraphs": [
            {"id": "p1", "text": "exact supported historical paragraph", "support_ids": ["claim_1"]},
            {"id": "p2", "text": "second historical paragraph", "support_ids": ["claim_2"]},
        ]}]},
    }
    task = {
        "description": (
            "original\n上一版交付物（必须在此基础上修改，不得只复述缺口）：\n"
            + json.dumps(previous, ensure_ascii=False)
            + "\n返工交付规则：仅恢复点名内容"
        ),
    }
    latest = {"chapter": {"sections": [{"heading": "Related Work", "paragraphs": [
        {"id": "p2", "text": "current second paragraph", "support_ids": ["claim_2"]},
    ]}]}}

    restored = thesis_chapter_service.restore_reviewed_paragraphs(
        task, latest, "请恢复 p1；其他段落保持当前版本。",
    )
    paragraphs = restored["result"]["chapter"]["sections"][0]["paragraphs"]

    assert [item["id"] for item in paragraphs] == ["p1", "p2"]
    assert paragraphs[0]["text"] == "exact supported historical paragraph"
    assert paragraphs[1]["text"] == "current second paragraph"
    assert restored["changes"] == [{"target": "p1", "operation": "restore_previous_exact"}]


def test_surgical_repair_understands_no_bound_support_review_language(monkeypatch):
    monkeypatch.setattr(ResearchClaimRepository, "get_by_run", lambda _run_id: [])
    latest = {"chapter": {"sections": [{"heading": "Pilot", "paragraphs": [{
        "id": "pilot", "paragraph_type": "claim", "support_ids": ["brief:methodology"],
        "text": "Each query has a single correct document. The measured MRR was 1.0.",
    }]}]}}
    review = {"quality_gates": {"layers": {"independent_review": {"issues": [{
        "target": "pilot",
        "reason": "No bound support directly states that each query has a single correct document.",
        "required_change": "No bound support directly states that each query has a single correct document.",
    }]}}}}

    repaired = thesis_chapter_service.surgical_repair(
        {"run_id": "run"}, latest, review,
    )

    text = repaired["result"]["chapter"]["sections"][0]["paragraphs"][0]["text"]
    assert text == "The measured MRR was 1.0."
    assert repaired["changes"][0]["operation"] == "delete"


def test_global_editorial_repair_is_deterministic_and_artifact_verified(monkeypatch):
    monkeypatch.setattr(
        thesis_chapter_service, "_canonical_artifact_text",
        lambda _run_id: '{"chunk_size":100,"overlap":30,"unit":"characters"}',
    )
    latest = {"chapter": {"sections": [{"heading": "Method", "paragraphs": [
        {"id": "p1", "text": ". Chunks use 100 tokens each.", "paragraph_type": "claim", "support_ids": ["brief:methodology"]},
        {"id": "p2", "text": "These conditions provide a minimal controlled comparison. Future work should test larger data.", "paragraph_type": "limitation", "support_ids": []},
        {"id": "p3", "text": "The conditions provide a minimal controlled comparison. However.", "paragraph_type": "interpretation", "support_ids": []},
    ]}]}}
    issues = [
        {"target": "p1", "reason": "unit mismatch", "required_change": "将 '100 tokens each' 改为 '100 characters each'"},
        {"target": "p2 p3", "reason": "未来工作错放且内容重复", "required_change": "删除未来工作与重复部分"},
        {"target": "p1", "reason": "type", "required_change": "从 'claim' 改为 'method'"},
    ]

    repaired = thesis_chapter_service.editorial_repair(
        {"run_id": "run"}, latest,
        {"quality_gates": {"layers": {"independent_review": {"issues": issues}}}},
    )
    paragraphs = repaired["result"]["chapter"]["sections"][0]["paragraphs"]

    assert paragraphs[0]["text"] == "Chunks use 100 characters each."
    assert paragraphs[0]["paragraph_type"] == "method"
    assert "Future work" not in paragraphs[1]["text"]
    assert "However." not in paragraphs[2]["text"]
    assert any(item["operation"] == "delete_duplicate" for item in repaired["changes"])


def test_surgical_repair_refuses_unit_deletion_that_conflicts_with_bound_artifact(monkeypatch):
    monkeypatch.setattr(ResearchClaimRepository, "get_by_run", lambda _run_id: [])
    monkeypatch.setattr(
        thesis_chapter_service, "_canonical_artifact_text",
        lambda _run_id: '{"chunk_size":100,"unit":"characters","avg_chunk_chars":86}',
    )
    latest = {"chapter": {"sections": [{"heading": "Pilot", "paragraphs": [{
        "id": "pilot", "paragraph_type": "method",
        "support_ids": ["experiment:verified"],
        "text": "The strategy uses 100 characters each.",
    }]}]}}
    issue = {
        "target": "pilot", "reason": "unit unsupported",
        "required_change": "删除 '100 characters each' 并改为 '100 each'",
    }

    repaired = thesis_chapter_service.surgical_repair(
        {"run_id": "run"}, latest,
        {"quality_gates": {"layers": {"independent_review": {"issues": [issue]}}}},
    )

    assert repaired["changes"] == []
    assert repaired["unresolved"] == [issue]
    assert repaired["result"]["chapter"]["sections"][0]["paragraphs"][0]["text"] == latest["chapter"]["sections"][0]["paragraphs"][0]["text"]


def test_surgical_repair_applies_only_artifact_verified_exact_replacement(monkeypatch):
    monkeypatch.setattr(ResearchClaimRepository, "get_by_run", lambda _run_id: [])
    monkeypatch.setattr(
        thesis_chapter_service, "_canonical_artifact_text",
        lambda _run_id: '{"chunk_size":100,"unit":"characters"}',
    )
    latest = {"chapter": {"sections": [{"heading": "Pilot", "paragraphs": [{
        "id": "pilot", "paragraph_type": "method", "support_ids": ["experiment:verified"],
        "text": "The method uses 100-token chunks.",
    }]}]}}
    review = {"quality_gates": {"layers": {"independent_review": {"issues": [{
        "target": "pilot", "reason": "artifact unit mismatch",
        "required_change": "将 '100-token chunks' 改为 '100-character chunks'",
    }]}}}}

    repaired = thesis_chapter_service.surgical_repair({"run_id": "run"}, latest, review)

    paragraph = repaired["result"]["chapter"]["sections"][0]["paragraphs"][0]
    assert paragraph["text"] == "The method uses 100-character chunks."
    assert repaired["changes"] == [{
        "target": "pilot", "operation": "replace_verified",
        "old": "100-token chunks", "new": "100-character chunks",
    }]


def test_advisor_cleanup_requires_named_paragraph_and_exact_quote(monkeypatch):
    monkeypatch.setattr(ResearchClaimRepository, "get_by_run", lambda _run_id: [])
    latest = {"chapter": {"sections": [{"heading": "Review", "paragraphs": [{
        "id": "p1", "paragraph_type": "claim", "support_ids": ["brief:scope"],
        "text": "Supported sentence. Unsupported historical sentence.",
    }]}]}}

    repaired = thesis_chapter_service.advisor_exact_cleanup(
        {"run_id": "run"}, latest,
        "请从 p1 删除 ‘Unsupported historical sentence.’，其余保持不变。",
    )

    paragraph = repaired["result"]["chapter"]["sections"][0]["paragraphs"][0]
    assert paragraph["text"] == "Supported sentence."
    assert repaired["changes"][0]["operation"] == "delete"
    assert thesis_chapter_service.advisor_exact_cleanup(
        {"run_id": "run"}, latest, "请改善 p1 的表达。",
    )["changes"] == []


def test_surgical_repair_uniquely_anchors_global_semantic_target_by_exact_quote(monkeypatch):
    monkeypatch.setattr(ResearchClaimRepository, "get_by_run", lambda _run_id: [])
    latest = {"chapter": {"sections": [{"heading": "Limit", "paragraphs": [
        {"id": "p1", "text": "Bounded limitation.", "paragraph_type": "limitation", "support_ids": []},
        {"id": "p2", "text": "Evidence statement. Unsupported extrapolation.", "paragraph_type": "claim", "support_ids": ["brief:scope"]},
    ]}]}}
    review = {"quality_gates": {"layers": {"independent_review": {"issues": [{
        "target": "scope extrapolation", "reason": "The phrase ‘Unsupported extrapolation.’ exceeds scope.",
        "required_change": "删除 ‘Unsupported extrapolation.’",
    }]}}}}

    repaired = thesis_chapter_service.surgical_repair({"run_id": "run"}, latest, review)

    assert repaired["result"]["chapter"]["sections"][0]["paragraphs"][1]["text"] == "Evidence statement."
    assert repaired["changes"][0]["target"] == "p2"


def test_advisor_artifact_conflict_arbitration_is_narrow(monkeypatch):
    monkeypatch.setattr(
        thesis_chapter_service, "_canonical_artifact_text",
        lambda _run_id: '{"chunk_size":100,"unit":"characters"}',
    )
    task = {"run_id": "run", "task_type": "thesis_chapter"}
    latest = {"chapter": {"sections": [{"paragraphs": [{
        "text": "The method uses 100-character chunks.",
    }]}]}}
    rejected = {
        "approved": False,
        "feedback": "误用 characters 代替 tokens，应修正为 100-token chunks。",
    }

    arbitrated = ReviewService._arbitrate_advisor(
        task, latest, rejected, {"passed": True},
    )

    assert arbitrated["approved"] is True
    assert arbitrated["advisor_artifact_conflict_overridden"] is True
    assert ReviewService._arbitrate_advisor(
        task, latest, {"approved": False, "feedback": "章节结论缺失。"}, {"passed": True},
    )["approved"] is False
    assert ReviewService._arbitrate_advisor(
        task, latest, rejected, {"passed": False},
    )["approved"] is False


def test_experiment_support_includes_frozen_protocol(monkeypatch):
    monkeypatch.setattr(ExperimentResultRepository, "get_by_run", lambda _run_id: [{
        "id": "result_verified", "protocol_id": "protocol_verified", "status": "completed",
        "summary": "verified", "metrics": {"rows": []},
    }])
    monkeypatch.setattr(ExperimentProtocolRepository, "get_by_id", lambda _protocol_id: {
        "research_question": "Does overlap improve retrieval?",
        "independent_variables": ["window_size", "overlap"],
        "dependent_variables": ["mrr_at_10"],
        "datasets": [{"name": "frozen benchmark"}],
        "metrics": ["mrr_at_10"],
        "baselines": [{"window_size": 100, "overlap": 0}],
        "method_details": {"unit": "character", "window_size": 100, "overlap": 30},
        "stopping_conditions": ["all queries evaluated"],
        "expected_risks": ["character boundaries may split semantics"],
    })

    support = thesis_chapter_service.artifact_support("run_verified")

    assert support[0]["protocol"]["method_details"]["unit"] == "character"
    assert support[0]["protocol"]["baselines"][0]["overlap"] == 0


def test_assembly_uses_latest_approved_revision_and_ignores_failed_drafts(tmp_path):
    run_id, run = _run_with_thesis(tmp_path, ["Analysis"])
    claim_id = f"claim_revision_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    ResearchClaimRepository.insert({
        "id": claim_id, "run_id": run_id, "statement": "A frozen artifact supports the analysis",
        "status": "supported", "evidence_ids": ["artifact"], "confidence": 0.9,
        "created_at": now, "updated_at": now,
    })
    root = thesis_chapter_service.ensure_tasks(run_id)[0]
    budget = thesis_chapter_service.spec_from_task(root)["word_budget"]
    old_output = _chapter_output("Analysis", budget, claim_id)
    old_output["chapter"]["sections"][0]["paragraphs"][0]["text"] += " OLD_ROOT_MARKER"
    TaskRepository.update_status(root["id"], "completed", outputs=[old_output])
    approved_output = _chapter_output("Analysis", budget, claim_id)
    approved_output["chapter"]["sections"][0]["paragraphs"][0]["text"] += " APPROVED_REVISION_MARKER"
    approved = {
        **root, "id": f"revision_approved_{uuid.uuid4().hex[:8]}", "title": "approved revision",
        "status": "completed", "outputs": [approved_output], "revision_of_task_id": root["id"],
        "created_at": "9999-01-01T00:00:00", "updated_at": "9999-01-01T00:00:00",
    }
    failed = {
        **root, "id": f"revision_failed_{uuid.uuid4().hex[:8]}", "title": "failed revision",
        "status": "failed", "outputs": [], "revision_of_task_id": root["id"],
        "created_at": "9999-01-02T00:00:00", "updated_at": "9999-01-02T00:00:00",
    }
    TaskRepository.insert(approved)
    TaskRepository.insert(failed)

    assert thesis_chapter_service.can_assemble(run_id) is True
    report = thesis_chapter_service.assemble(run, "Revision Thesis")
    assert "APPROVED_REVISION_MARKER" in report
    assert "OLD_ROOT_MARKER" not in report


def test_deterministic_thesis_assembly_adds_verified_citations_and_traceability(tmp_path):
    run_id, run = _run_with_thesis(tmp_path, ["分析"])
    claim_id = f"claim_grounded_{uuid.uuid4().hex[:8]}"
    source_id = f"source_{uuid.uuid4().hex[:8]}"
    link_id = f"link_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    ResearchClaimRepository.insert({
        "id": claim_id, "run_id": run_id, "statement": "史料在冻结语境下支持该解释",
        "status": "supported", "evidence_ids": [source_id], "confidence": 0.9,
        "created_at": now, "updated_at": now,
    })
    EvidenceRepository.upsert_source({
        "id": source_id, "run_id": run_id, "title": "Verified Source", "authors": "Author",
        "year": 2024, "venue": "Archive", "url": "https://example.org/source", "source_type": "primary",
        "metadata": {"citation_eligible": True}, "created_at": now,
    })
    EvidenceRepository.insert_link({
        "id": link_id, "run_id": run_id, "claim_id": claim_id, "source_id": source_id,
        "excerpt_id": None, "relation_type": "supports", "confidence": 0.9,
        "rationale": "verified", "created_at": now,
    })
    task = thesis_chapter_service.ensure_tasks(run_id)[0]
    spec = thesis_chapter_service.spec_from_task(task)
    output = _chapter_output("分析", spec["word_budget"], claim_id)
    TaskRepository.update_status(task["id"], "completed", outputs=[output])

    report = thesis_chapter_service.assemble(run, "可追溯硕士论文")

    assert "**交付等级:** `master_thesis_candidate`" in report
    assert "[1]" in report
    assert "Verified Source" in report
    assert f"`{claim_id}`" in report
    assert "## 可追溯附录" in report
    assert "**测试大学**" in report
    assert "## 目录" in report
    assert "## 研究与人工智能来源声明" in report


def test_delivery_status_promotes_only_after_master_thesis_gate():
    report = "# Thesis\n\n**交付等级:** `master_thesis_candidate`"
    assert "`master_thesis`" in ReportService._promote_delivery_status(
        report, {"master_thesis_ready": True}
    )
    assert "`master_thesis_candidate`" in ReportService._promote_delivery_status(
        report, {"master_thesis_ready": False}
    )


def test_verified_final_thesis_completes_canonical_report_task(monkeypatch):
    tasks = [
        {
            "id": "report_root", "task_type": "report_writing", "status": "failed",
            "revision_of_task_id": None, "outputs": [],
        },
        {
            "id": "report_revision", "task_type": "report_writing", "status": "failed",
            "revision_of_task_id": "report_root", "outputs": [],
        },
    ]
    updates = []
    monkeypatch.setattr(TaskRepository, "get_all", lambda run_id=None: tasks)
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda task_id, status, **kwargs: updates.append((task_id, status, kwargs)),
    )

    quality = {"passed": True, "master_thesis_ready": True}
    ReportService._complete_report_writing_tasks("run_verified", quality)

    assert len(updates) == 1
    task_id, status, payload = updates[0]
    assert (task_id, status) == ("report_root", "completed")
    assert payload["review_result"]["quality_gates"] == quality
    assert payload["outputs"][-1]["final_report_id"] == "final_report_run_verified"


def test_harvard_contract_renders_author_date_citations(tmp_path):
    run_id, run = _run_with_thesis(tmp_path, ["Analysis"], citation_style="Harvard")
    claim_id = f"claim_harvard_{uuid.uuid4().hex[:8]}"
    source_id = f"source_harvard_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    ResearchClaimRepository.insert({
        "id": claim_id, "run_id": run_id, "statement": "Grounded result", "status": "supported",
        "evidence_ids": [source_id], "confidence": 0.9, "created_at": now, "updated_at": now,
    })
    EvidenceRepository.upsert_source({
        "id": source_id, "run_id": run_id, "title": "Verified Paper", "authors": "Smith, Jane; Lee, Ann",
        "year": 2024, "venue": "Journal", "doi": "10.1000/verified", "source_type": "paper",
        "metadata": {"citation_eligible": True}, "created_at": now,
    })
    EvidenceRepository.insert_link({
        "id": f"link_{uuid.uuid4().hex[:8]}", "run_id": run_id, "claim_id": claim_id,
        "source_id": source_id, "excerpt_id": None, "relation_type": "supports", "confidence": 0.9,
        "rationale": "verified", "created_at": now,
    })
    task = thesis_chapter_service.ensure_tasks(run_id)[0]
    TaskRepository.update_status(
        task["id"], "completed", outputs=[_chapter_output("Analysis", thesis_chapter_service.spec_from_task(task)["word_budget"], claim_id)],
    )

    report = thesis_chapter_service.assemble(run, "Harvard Thesis")

    assert "(Smith et al., 2024)" in report
    assert "- Smith, Jane; Lee, Ann (2024). Verified Paper." in report
    assert "[1]" not in report
