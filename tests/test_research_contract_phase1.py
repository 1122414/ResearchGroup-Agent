import uuid
from datetime import datetime

import pytest

from backend.app.core.config import settings
from backend.app.services.research_contract_service import research_contract_service
from backend.app.services.research_state_service import research_state_service
from backend.app.services.task_decomposer import task_decomposer
from backend.app.storage import init_db
from backend.app.storage.repositories import RunRepository


@pytest.fixture(autouse=True)
def _db():
    init_db()


def _run() -> dict:
    now = datetime.now().isoformat()
    run = {
        "id": f"run_contract_{uuid.uuid4().hex[:8]}",
        "research_goal": "比较两种检索策略在公开问答数据上的效果并分析失败案例",
        "status": "created",
        "created_at": now,
        "updated_at": now,
    }
    RunRepository.insert(run)
    research_state_service.ensure_initialized(run)
    return run


@pytest.mark.asyncio
async def test_contract_has_scope_falsification_and_milestones(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    run = _run()

    contract = await research_contract_service.ensure_contract(run)
    state = research_state_service.get_state(run["id"])

    assert contract["ready"] is True
    assert contract["brief"]["scope_out"]
    assert len(contract["brief"]["subquestions"]) >= 2
    assert all(item["falsification_criterion"] for item in contract["hypotheses"])
    assert {item["milestone_key"] for item in state["milestones"]} == {
        "framing_frozen", "search_protocol_frozen", "evidence_sufficient",
        "experiment_protocol_frozen", "replication_passed", "report_verified",
        "methodology_frozen", "resources_ready", "ethics_cleared", "thesis_requirements_frozen",
    }


@pytest.mark.asyncio
async def test_decomposed_tasks_link_back_to_contract(monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    run = _run()
    contract = await research_contract_service.ensure_contract(run)
    research_contract_service.freeze(run["id"])
    contract["brief"] = research_state_service.get_state(run["id"])["brief"]

    tasks = await task_decomposer.decompose(run["research_goal"], run["id"], contract)

    assert tasks
    assert all(task["subquestion_id"] for task in tasks)
    assert all(task["hypothesis_id"] for task in tasks)
    assert all(task["milestone_id"] for task in tasks)


def test_invalid_contract_is_revision_state():
    run = _run()
    revised = research_contract_service.revise(
        run["id"],
        {"primary_question": "太宽", "subquestions": [], "hypotheses": []},
    )
    assert revised["ready"] is False
    assert revised["brief"]["approval_status"] == "needs_revision"
    assert revised["errors"]


def test_contract_type_overrides_keyword_mode_detection():
    assert task_decomposer.detect_mode("提出并验证一个新方法", {"research_type": "survey"}) == "survey"


def test_supported_rag_contract_has_bounded_deterministic_fallback():
    fallback = research_contract_service._supported_domain_fallback("比较 RAG 检索切分的 MRR")
    assert fallback is not None
    assert research_contract_service.validate(fallback, fallback["hypotheses"]) == []
    assert research_contract_service._supported_domain_fallback("细胞培养湿实验") is None


def test_contract_validation_rejects_string_hypothesis_without_crashing():
    fallback = research_contract_service._supported_domain_fallback("比较 RAG 检索切分的 MRR")
    assert fallback is not None
    errors = research_contract_service.validate(fallback, ["重叠切分会提升 MRR"])
    assert "hypothesis[0] 必须是对象" in errors
