import uuid
import json
from datetime import datetime

import pytest

from backend.app.services.report_service import ReportService
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
    assert "硬性最低 700 词" in calls[0]["prompt"]
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
    monkeypatch.setattr(thesis_chapter_service, "validate_output", lambda *_args: [])

    result = await TaskExecutor()._expand_short_chapter(
        FakeLLM(), "unused", task, "writer",
        {"summary": "original", "claims": [], "chapter": {"sections": []}},
    )

    assert len(calls) == 2
    assert result["chapter"]["marker"] == "longer"


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
