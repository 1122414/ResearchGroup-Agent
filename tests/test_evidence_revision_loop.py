import pytest

from backend.app.core.config import settings
from backend.app.services.browser_research_service import BrowserResearchService, BrowserVerificationResult
from backend.app.services.research_integrity_service import research_integrity_service
from backend.app.services.task_recovery_service import task_recovery_service
from backend.app.storage.repositories import TaskRepository


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
