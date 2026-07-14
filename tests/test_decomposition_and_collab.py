import uuid
from datetime import datetime

import pytest

from backend.app.services.task_decomposer import task_decomposer
from backend.app.services.task_executor import task_executor
from backend.app.storage import init_db
from backend.app.storage.repositories import (
    ResearchHypothesisRepository,
    SubAgentRepository,
    TaskRepository,
)


@pytest.fixture(autouse=True)
def _db():
    init_db()


def test_detect_mode():
    assert task_decomposer.detect_mode("调研 GitHub 多 Agent 框架现状") == "survey"
    assert task_decomposer.detect_mode("提出一种更快的检索方法并验证") == "paper"


@pytest.mark.asyncio
async def test_survey_decomposition_drops_experiments_and_seeds_hypothesis():
    run_id = f"run_dec_{uuid.uuid4().hex[:6]}"
    tasks = await task_decomposer.decompose("调研多 Agent 协作系统的现状与对比", run_id)
    assert tasks
    assert all(task["task_type"] != "experiment_design" for task in tasks)
    hypotheses = ResearchHypothesisRepository.get_by_run(run_id)
    assert any("综述" in h["rationale"] or "权衡" in h["statement"] for h in hypotheses)


def test_collaboration_context_includes_subagent_results():
    run_id = f"run_collab_{uuid.uuid4().hex[:6]}"
    task = {
        "id": f"task_{uuid.uuid4().hex[:6]}",
        "run_id": run_id,
        "title": "T",
        "description": "d",
        "task_type": "literature_survey",
        "required_skills": {},
        "collaborator_agents": ["grad_analyst"],
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    TaskRepository.insert(task)
    SubAgentRepository.insert(
        {
            "id": f"subagent_{uuid.uuid4().hex[:6]}",
            "parent_agent": "grad_researcher",
            "task_id": task["id"],
            "task": "help",
            "context": "",
            "expected_output_schema": {},
            "status": "completed",
            "result": {"summary": "subagent contribution X", "findings": []},
        }
    )
    context = task_executor._collaboration_context(
        task,
        [{"collaborator_id": "grad_analyst", "output": {"summary": "independent critique Y"}}],
    )
    assert "协作中间结果" in context
    assert "subagent contribution X" in context
    assert "grad_analyst" in context
    assert "independent critique Y" in context
