import pytest

from backend.app.core.config import settings
from backend.app.services.browser_research_service import BrowserResearchService, BrowserVerificationResult
from backend.app.services.evidence_pipeline_service import EvidencePipelineService
from backend.app.services.research_integrity_service import research_integrity_service
from backend.app.services.review_service import review_service
from backend.app.services.run_event_service import run_event_service
from backend.app.services.run_execution_service import run_execution_service
from backend.app.services.task_recovery_service import task_recovery_service
from backend.app.storage.repositories import EvidenceRepository, RunRepository, TaskRepository


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
