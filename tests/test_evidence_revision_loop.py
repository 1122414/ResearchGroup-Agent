import pytest

from backend.app.core.config import settings
from backend.app.services.browser_research_service import BrowserResearchService, BrowserVerificationResult
from backend.app.services.browser_research_service import BrowserDiscoveryResult
from backend.app.services.evidence_pipeline_service import EvidencePipelineService
from backend.app.services.research_integrity_service import research_integrity_service
from backend.app.services.review_service import review_service
from backend.app.services.run_event_service import run_event_service
from backend.app.services.run_execution_service import run_execution_service
from backend.app.services.task_graph_service import task_graph_service
from backend.app.services.task_recovery_service import task_recovery_service
from backend.app.services.thesis_chapter_service import thesis_chapter_service
from backend.app.storage.repositories import (
    EvidenceRepository, RunEventRepository, RunRepository,
    TaskDependencyRepository, TaskRepository,
)


@pytest.mark.asyncio
async def test_browser_verification_keeps_trusted_metadata_when_verdicts_are_missing(monkeypatch):
    monkeypatch.setattr(settings, "browser_research_enabled", True)
    monkeypatch.setattr(settings, "browser_research_provider_mode", "browser_use")
    monkeypatch.setattr(settings, "browser_verification_enabled", True)
    monkeypatch.setattr(settings, "browser_verification_required", True)
    monkeypatch.setattr(settings, "browser_use_max_candidates", 1)

    async def fake_run_agent(*args, **kwargs):
        return type("History", (), {"structured_output": BrowserVerificationResult(verdicts=[])})()

    monkeypatch.setattr(BrowserResearchService, "_run_agent", fake_run_agent)

    sources = [
        {
            "id": "web_1",
            "title": "Generic search result",
            "url": "https://example.com/generic",
            "source_type": "web",
            "metadata": {"provider": "tavily"},
        },
        {
            "id": "paper_1",
            "title": "Telegram fraud study",
            "doi": "10.1000/example",
            "url": "https://doi.org/10.1000/example",
            "source_type": "paper",
            "metadata": {"provider": "crossref"},
        },
        {
            "id": "paper_2",
            "title": "Online scam detection",
            "url": "https://arxiv.org/abs/2501.00001",
            "source_type": "paper",
            "metadata": {"provider": "arxiv"},
        },
    ]

    verified = await BrowserResearchService().verify_candidates("Telegram scam response", sources)

    assert [source["id"] for source in verified] == ["web_1", "paper_1", "paper_2"]
    assert verified[0]["metadata"]["browser_verification"]["fallback"] == "search_result_metadata"
    assert all(
        source["metadata"]["browser_verification"]["fallback"] == "trusted_scholarly_metadata"
        for source in verified[1:]
    )


@pytest.mark.asyncio
async def test_browser_discovery_drops_structured_output_rejected_by_judge(monkeypatch):
    monkeypatch.setattr(settings, "browser_research_enabled", True)
    monkeypatch.setattr(settings, "browser_research_provider_mode", "browser_use")

    class JudgedFailure:
        structured_output = BrowserDiscoveryResult(sources=[{
            "title": "Invented from a failed download",
            "url": "https://doi.org/10.1000/failed",
            "evidence": "not visible on a page",
        }])

        @staticmethod
        def is_validated():
            return False

    async def fake_run_agent(*_args, **_kwargs):
        return JudgedFailure()

    monkeypatch.setattr(BrowserResearchService, "_run_agent", fake_run_agent)

    assert await BrowserResearchService().discover("failed source") == []


def test_literature_revision_reuses_frozen_fulltext_pool(monkeypatch):
    service = EvidencePipelineService()
    sources = [{"id": "source_1"}, {"id": "source_2"}]
    excerpts = [
        {"id": "passage_1", "source_id": "source_1", "excerpt": "a"},
        {"id": "passage_2", "source_id": "source_2", "excerpt": "b"},
    ]
    monkeypatch.setattr(settings, "literature_min_grounded_sources", 2)
    monkeypatch.setattr(service, "_cumulative_grounded_evidence", lambda *_args: (sources, excerpts))
    monkeypatch.setattr(EvidenceRepository, "get_by_run", lambda _run_id: {
        "assessments": [{"source_id": "source_1"}, {"source_id": "source_2"}],
    })

    bundle = service._frozen_revision_bundle({
        "id": "revision", "run_id": "run_1", "revision_of_task_id": "root",
    }, "query")

    assert bundle["mode"] == "frozen_revision_evidence"
    assert bundle["sources"] == sources
    assert bundle["excerpts"] == excerpts
    assert bundle["search_metrics"]["reused_frozen_pool"] is True
    assert bundle["search_attempts"] == []


def test_literature_revision_expands_search_when_review_requests_new_sources(monkeypatch):
    service = EvidencePipelineService()
    monkeypatch.setattr(TaskRepository, "get_by_id", lambda _task_id: {
        "review_feedback": "请重新检索并补充更多相关的可核验来源",
    })

    bundle = service._frozen_revision_bundle({
        "id": "revision", "run_id": "run_1", "revision_of_task_id": "root",
    }, "education spending")

    assert bundle is None


def test_frozen_evidence_pool_is_ranked_for_current_question(monkeypatch):
    service = EvidencePipelineService()
    sources = [
        {"id": "irrelevant", "title": "Particle physics report", "metadata": {}},
        {"id": "relevant", "title": "Government education expenditure by income group", "metadata": {}},
    ]
    excerpts = [
        {"id": "p1", "source_id": "irrelevant", "excerpt": "physics"},
        {"id": "p2", "source_id": "relevant", "excerpt": "education expenditure"},
    ]
    monkeypatch.setattr(settings, "literature_min_grounded_sources", 1)
    monkeypatch.setattr(service, "_cumulative_grounded_evidence", lambda *_args: (sources, excerpts))
    monkeypatch.setattr(EvidenceRepository, "get_by_run", lambda _run_id: {"assessments": []})

    bundle = service._frozen_revision_bundle({
        "id": "revision", "run_id": "run_1", "revision_of_task_id": "root",
    }, "government education expenditure income group")

    assert [item["id"] for item in bundle["sources"]] == ["relevant"]
    assert [item["id"] for item in bundle["excerpts"]] == ["p2"]


def test_loop_claim_synthesis_reuses_verified_frozen_evidence(monkeypatch):
    service = EvidencePipelineService()
    sources = [{"id": "source_1", "title": "Education finance"}]
    excerpts = [{"id": "p1", "source_id": "source_1", "excerpt": "education expenditure"}]
    monkeypatch.setattr(settings, "literature_min_grounded_sources", 1)
    monkeypatch.setattr(service, "_cumulative_grounded_evidence", lambda *_args: (sources, excerpts))
    monkeypatch.setattr(EvidenceRepository, "get_by_run", lambda _run_id: {"assessments": []})

    bundle = service._frozen_revision_bundle({
        "id": "loop", "run_id": "run_1", "title": "[循环R1] 补足论文证据",
        "task_type": "literature_survey",
        "description": '{"target":{"type":"thesis_evidence_coverage"}}',
    }, "education expenditure")

    assert bundle["mode"] == "frozen_revision_evidence"
    assert bundle["search_metrics"]["reused_frozen_pool"] is True


def test_revision_task_does_not_reuse_itself_as_next_revision(monkeypatch):
    monkeypatch.setattr(settings, "task_max_revision_rounds", 1)

    root_task = {
        "id": "task_root",
        "run_id": "run_loop",
        "title": "Literature task",
        "description": "Collect sources",
        "task_type": "literature_survey",
        "required_skills": {},
        "priority": 5,
        "complexity": 5,
        "decomposability": 5,
        "owner_agent": "grad_researcher",
        "collaborator_agents": [],
        "assignment_info": {},
        "parallelizable": True,
        "is_critical_path": False,
        "subtasks": ["task_revision_existing"],
    }
    current_revision = {
        **root_task,
        "id": "task_revision_existing",
        "revision_of_task_id": "task_root",
        "status": "need_revision",
    }

    monkeypatch.setattr(task_recovery_service, "_root_task", lambda task: root_task)
    monkeypatch.setattr(TaskRepository, "get_all", lambda run_id=None: [root_task, current_revision])

    assert task_recovery_service.create_revision_task(current_revision, "still not enough evidence") is None


def test_revision_description_preserves_structured_plan_and_previous_delivery():
    root = {"title": "冻结实验方案", "description": "提交完整可复现实验协议"}
    latest = {"outputs": [{"summary": "上一版", "findings": ["seed=42"]}]}
    review = {
        "feedback": "独立审稿未通过",
        "revision_plan": [
            {"issue": "种子含义不清", "required_change": "固定执行种子并说明 bootstrap 种子"}
        ],
    }

    description = task_recovery_service._revision_description(root, latest, review)

    assert "逐项修改清单" in description
    assert "固定执行种子" in description
    assert "上一版交付物" in description
    assert "seed=42" in description
    assert "不得只复述缺口" in description


def test_revision_description_accumulates_prior_review_requirements(monkeypatch):
    root = {
        "id": "root", "run_id": "run", "title": "文献综述", "description": "提交综述",
        "created_at": "2026-01-01",
        "review_result": {"revision_plan": [{
            "layer": "independent_review", "issue": "例外不等于上升", "required_change": "改为未下降",
        }]},
    }
    latest = {
        "id": "revision", "run_id": "run", "revision_of_task_id": "root",
        "created_at": "2026-01-02", "outputs": [{"summary": "已修订"}],
        "review_result": {"revision_plan": [{
            "layer": "independent_review", "issue": "元数据无依据", "required_change": "删除该 claim",
        }]},
    }
    monkeypatch.setattr(TaskRepository, "get_all", lambda run_id=None: [root, latest])

    description = task_recovery_service._revision_description(
        root, latest, {"feedback": "继续修订", "revision_plan": []},
    )

    assert "累计返工约束" in description
    assert "改为未下降" in description
    assert "删除该 claim" in description


def test_revision_description_drops_bulky_evidence_objects():
    root = {"title": "文献综述", "description": "提交有依据的结论"}
    latest = {"outputs": [{
        "summary": "上一版", "claims": [{"statement": "c"}],
        "papers_read": [{"metadata": {"raw": "x" * 20000}}],
        "evidence_excerpts": [{"excerpt": "y" * 20000}],
        "evidence_assessments": [{"notes": "z" * 20000}],
    }]}
    description = task_recovery_service._revision_description(root, latest, "补齐引用")
    assert "上一版" in description
    assert '"claims"' in description
    assert "papers_read" not in description
    assert "evidence_excerpts" not in description
    assert len(description) < 7000


def test_thesis_revision_description_keeps_complete_previous_chapter():
    root = {
        "title": "论文结果章", "description": "修订结果章",
        "task_type": "thesis_chapter",
    }
    latest = {"outputs": [{
        "summary": "上一版",
        "chapter": {
            "name": "Results",
            "sections": [{
                "heading": "最后一节",
                "paragraphs": [{
                    "id": "p-last", "text": "需要定点修改的末尾段落",
                    "paragraph_type": "claim", "support_ids": ["claim-1"],
                }],
            }],
        },
    }]}

    description = task_recovery_service._revision_description(root, latest, "修改末尾段落")

    assert '"chapter"' in description
    assert "p-last" in description
    assert "需要定点修改的末尾段落" in description


@pytest.mark.asyncio
async def test_review_transport_retry_does_not_consume_chapter_attempt(monkeypatch):
    task = {
        "id": "chapter_transport", "run_id": "run_transport", "title": "Introduction",
        "task_type": "thesis_chapter", "status": "running", "attempt_count": 4,
        "owner_agent": "writer", "outputs": [{"summary": "complete chapter"}],
    }
    review_calls = 0
    events = []

    async def failed_transport_review(_task):
        nonlocal review_calls
        review_calls += 1
        return {
            "approved": False, "requires_revision": False,
            "review_mode": "independent_review_transport_failure",
            "feedback": "empty reviewer response",
        }

    def update_status(_task_id, status, **fields):
        task.update(status=status, **fields)

    monkeypatch.setattr(RunRepository, "get_by_id", lambda _run_id: {"status": "executing"})
    monkeypatch.setattr(TaskRepository, "get_by_id", lambda _task_id: dict(task))
    monkeypatch.setattr(TaskRepository, "update_status", update_status)
    monkeypatch.setattr(review_service, "review", failed_transport_review)
    monkeypatch.setattr(run_event_service, "emit", lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type))

    await run_execution_service._review_task_batch("run_transport", [dict(task)])

    assert review_calls == 2
    assert task["status"] == "failed"
    assert task["attempt_count"] == 4
    assert "review.transport_retry" in events
    assert "review.transport_exhausted" in events


def test_unactionable_delete_migration_reopens_only_review(monkeypatch):
    task = {
        "id": "chapter_unlocated", "run_id": "run_unlocated", "title": "Literature Review",
        "task_type": "thesis_chapter", "status": "failed", "attempt_count": 6,
        "owner_agent": "writer", "revision_of_task_id": "chapter_root",
        "outputs": [{
            "chapter": {"sections": [{"paragraphs": [{
                "id": "p1", "text": "A bounded and supported paragraph.",
            }]}]},
        }],
        "review_result": {"quality_gates": {"layers": {"independent_review": {
            "reviewer": "independent_reviewer_model_paragraph_audit_v2",
            "issues": [{
                "target": "p1", "reason": "",
                "required_change": "Delete the unsupported phrase.",
            }],
        }}}},
    }
    updates = []
    events = []

    monkeypatch.setattr(
        RunEventRepository, "count_task_events",
        lambda _run_id, _task_id, _event_type: 0,
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda task_id, status, **fields: updates.append((task_id, status, fields)),
    )
    monkeypatch.setattr(
        run_execution_service, "_revive_dependency_descendants",
        lambda run_id, root_id: events.append(("revive", run_id, root_id)),
    )
    monkeypatch.setattr(
        run_event_service, "emit",
        lambda run_id, event_type, *_args, **_kwargs: events.append((event_type, run_id)),
    )

    changed = run_execution_service._retry_unactionable_audit_migration([task])

    assert changed is True
    assert updates == [("chapter_unlocated", "running", {
        "blocked_reason": None, "review_result": None, "review_feedback": None,
    })]
    assert ("revive", "run_unlocated", "chapter_root") in events
    assert ("review.actionable_issue_migration", "run_unlocated") in events


def test_unactionable_delete_migration_selects_latest_revision(monkeypatch):
    def revision(task_id, created_at):
        return {
            "id": task_id, "run_id": "run_family", "title": "Literature Review",
            "task_type": "thesis_chapter", "status": "failed", "attempt_count": 6,
            "owner_agent": "writer", "revision_of_task_id": "chapter_root",
            "created_at": created_at,
            "outputs": [{"chapter": {"sections": [{"paragraphs": [{
                "id": "p1", "text": "A bounded and supported paragraph.",
            }]}]}}],
            "review_result": {"quality_gates": {"layers": {"independent_review": {
                "reviewer": "independent_reviewer_model_paragraph_audit_v2",
                "issues": [{
                    "target": "p1", "reason": "",
                    "required_change": "Delete the unsupported phrase.",
                }],
            }}}},
        }

    older = revision("revision_old", "2026-07-17T10:00:00")
    latest = revision("revision_latest", "2026-07-17T11:00:00")
    updates = []

    monkeypatch.setattr(
        RunEventRepository, "count_task_events",
        lambda _run_id, _task_id, _event_type: 0,
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda task_id, status, **fields: updates.append((task_id, status)),
    )
    monkeypatch.setattr(
        run_execution_service, "_revive_dependency_descendants",
        lambda *_args: None,
    )
    monkeypatch.setattr(run_event_service, "emit", lambda *_args, **_kwargs: None)

    assert run_execution_service._retry_unactionable_audit_migration([older, latest]) is True
    assert updates == [("revision_latest", "running")]


def test_unactionable_delete_migration_recovers_latest_archived_before_review(monkeypatch):
    task = {
        "id": "revision_latest", "run_id": "run_family", "title": "Literature Review",
        "task_type": "thesis_chapter", "status": "archived", "attempt_count": 6,
        "owner_agent": "writer", "revision_of_task_id": "chapter_root",
        "created_at": "2026-07-17T11:00:00",
        "outputs": [{"chapter": {"sections": [{"paragraphs": [{
            "id": "p1", "text": "A bounded and supported paragraph.",
        }]}]}}],
        "review_result": None,
    }
    updates = []
    events = []

    def event_count(_run_id, _task_id, event_type):
        return int(event_type == "review.actionable_issue_migration")

    monkeypatch.setattr(RunEventRepository, "count_task_events", event_count)
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda task_id, status, **fields: updates.append((task_id, status)),
    )
    monkeypatch.setattr(
        run_execution_service, "_revive_dependency_descendants",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        run_event_service, "emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_unactionable_audit_migration([task]) is True
    assert updates == [("revision_latest", "running")]
    assert events == ["review.actionable_issue_latest_migration"]


def test_unactionable_delete_migration_recovers_after_old_task_graph_archive(monkeypatch):
    task = {
        "id": "revision_latest", "run_id": "run_family", "title": "Literature Review",
        "task_type": "thesis_chapter", "status": "archived", "attempt_count": 6,
        "owner_agent": "writer", "revision_of_task_id": "chapter_root",
        "created_at": "2026-07-17T11:00:00",
        "outputs": [{"chapter": {"sections": [{"paragraphs": [{
            "id": "p1", "text": "A bounded and supported paragraph.",
        }]}]}}],
        "review_result": None,
    }
    updates = []
    events = []

    def event_count(_run_id, _task_id, event_type):
        return int(event_type in {
            "review.actionable_issue_migration",
            "review.actionable_issue_latest_migration",
        })

    monkeypatch.setattr(RunEventRepository, "count_task_events", event_count)
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda task_id, status, **fields: updates.append((task_id, status)),
    )
    monkeypatch.setattr(
        run_execution_service, "_revive_dependency_descendants",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        run_event_service, "emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_unactionable_audit_migration([task]) is True
    assert updates == [("revision_latest", "running")]
    assert events == ["review.latest_branch_guard_migration"]


def test_writing_flow_keeps_only_latest_thesis_revision_executable(monkeypatch):
    tasks = [
        {
            "id": "chapter_root", "task_type": "thesis_chapter",
            "status": "failed", "created_at": "2026-07-17T09:00:00",
        },
        {
            "id": "revision_old", "revision_of_task_id": "chapter_root",
            "task_type": "thesis_chapter", "status": "waiting_review",
            "created_at": "2026-07-17T10:00:00",
        },
        {
            "id": "revision_latest", "revision_of_task_id": "chapter_root",
            "task_type": "thesis_chapter", "status": "running",
            "created_at": "2026-07-17T11:00:00",
        },
        {
            "id": "report", "task_type": "report_writing",
            "status": "failed", "created_at": "2026-07-17T09:00:00",
        },
    ]
    updates = []
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda task_id, status, **fields: updates.append((task_id, status)),
    )

    active = run_execution_service._latest_writing_family_members(tasks)
    changed = run_execution_service._archive_nonlatest_writing_branches(tasks)

    assert {task["id"] for task in active} == {"revision_latest", "report"}
    assert changed is True
    assert updates == [("revision_old", "archived")]


def test_task_graph_allows_only_latest_thesis_revision_under_failed_root(monkeypatch):
    tasks = [
        {
            "id": "chapter_root", "task_type": "thesis_chapter",
            "status": "failed", "created_at": "2026-07-17T09:00:00",
        },
        {
            "id": "revision_old", "revision_of_task_id": "chapter_root",
            "task_type": "thesis_chapter", "status": "pending",
            "created_at": "2026-07-17T10:00:00",
        },
        {
            "id": "revision_latest", "revision_of_task_id": "chapter_root",
            "task_type": "thesis_chapter", "status": "pending",
            "created_at": "2026-07-17T11:00:00",
        },
    ]
    updates = []
    monkeypatch.setattr(
        TaskDependencyRepository, "get_for_task", lambda _task_id: [],
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda task_id, status, **fields: updates.append((task_id, status)),
    )

    ready = task_graph_service.ready_tasks(tasks)

    assert [task["id"] for task in ready] == ["revision_latest"]
    assert updates == [("revision_old", "archived")]


def test_writing_recoveries_run_before_terminal_decision(monkeypatch):
    calls = []
    method_names = (
        "_retry_distributed_length_migration",
        "_retry_first_paragraph_audit",
        "_retry_structural_floor_migration",
        "_retry_epistemic_audit_migration",
        "_retry_global_scope_migration",
        "_retry_advisor_artifact_conflict_migration",
        "_retry_unactionable_audit_migration",
        "_retry_advisor_chapter_contract_cleanup",
        "_retry_advisor_paragraph_restoration",
        "_retry_advisor_exact_cleanup",
        "_retry_surgical_chapter_repair",
        "_retry_transient_writing_failures",
    )
    for name in method_names:
        monkeypatch.setattr(
            run_execution_service,
            name,
            lambda _tasks, method=name: calls.append(method) or method == "_retry_surgical_chapter_repair",
        )

    changed = run_execution_service._apply_writing_recoveries([{"id": "latest"}])

    assert changed is True
    assert calls == list(method_names)


def test_advisor_chapter_claims_conflict_is_overridden_after_prose_cleanup(monkeypatch):
    task = {"id": "chapter", "task_type": "thesis_chapter"}
    latest = {"claims": [], "chapter": {"sections": []}}
    review = {
        "approved": False,
        "feedback": "The claims field is empty; claims must be included to show evidence binding.",
    }
    monkeypatch.setattr(
        thesis_chapter_service,
        "advisor_feedback_misreads_chapter_claims",
        lambda *_args: True,
    )

    result = review_service._arbitrate_advisor(
        task, latest, review, {"passed": True},
    )

    assert result["approved"] is True
    assert result["advisor_chapter_claims_conflict_overridden"] is True


def test_malformed_prose_cleanup_detects_deletion_fragments():
    assert thesis_chapter_service._is_malformed_sentence(
        "The present study by delivering a clear descriptive estimate."
    )
    assert thesis_chapter_service._is_malformed_sentence(
        "This finding reflects the broader context that."
    )


def test_practical_high_complexity_report_requires_one_source(monkeypatch):
    monkeypatch.setattr(settings, "literature_require_grounded_sources", True)
    monkeypatch.setattr(settings, "literature_min_grounded_sources", 2)

    task = {
        "title": "调研 Telegram 电诈团伙常用诈骗方式以及应对方法",
        "description": "形成实务应对报告",
        "complexity": 9,
    }

    assert research_integrity_service.evidence_scope(task, task["title"]) == "practical_brief"
    assert research_integrity_service.required_grounded_source_count(task, task["title"]) == 1
