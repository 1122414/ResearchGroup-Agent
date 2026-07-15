import json
import uuid
from datetime import datetime

import pytest

from backend.app.services.task_decomposer import task_decomposer
from backend.app.services.task_executor import task_executor
from backend.app.services.scientific_quality_gate_service import scientific_quality_gate_service
from backend.app.storage import init_db
from backend.app.storage.repositories import (
    OutputRepository,
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


def test_task_parser_accepts_provider_json_object_wrapper_and_legacy_array():
    task = {"title": "真实任务", "task_type": "literature_survey"}

    assert task_decomposer._parse_response(json.dumps({"tasks": [task]})) == [task]
    assert task_decomposer._parse_response(json.dumps([task])) == [task]
    assert task_decomposer._parse_response(json.dumps({"items": [task]})) == []


def test_inverted_design_and_execution_roles_are_normalized():
    tasks = [
        {
            "title": "实验设计冻结：切分策略与评估方案",
            "description": "冻结参数、停止条件和 artifact 清单，不执行实验。",
            "task_type": "experiment_design",
        },
        {
            "title": "系统实现与实验执行",
            "description": "实现 pipeline，执行至少三次运行并生成 artifact hash 和结果文件。",
            "task_type": "system_design",
        },
    ]
    result = task_decomposer._normalize_inverted_experiment_roles(tasks)
    assert result[0]["task_type"] == "system_design"
    assert result[1]["task_type"] == "experiment_design"


def test_valid_design_and_execution_roles_are_left_unchanged():
    tasks = [
        {"title": "系统设计", "description": "冻结接口与参数", "task_type": "system_design"},
        {"title": "实验执行", "description": "执行实验并生成结果文件", "task_type": "experiment_design"},
    ]
    assert task_decomposer._normalize_inverted_experiment_roles(tasks) == tasks


def test_supported_retrieval_tasks_cannot_drift_to_bm25():
    tasks = [
        {
            "description": "使用 BM25 检索器并安装 rank_bm25",
            "task_type": "system_design",
            "hypothesis_id": "h1",
        },
        {
            "description": "运行 embedding 检索实验",
            "task_type": "experiment_design",
            "hypothesis_id": "h1",
        },
    ]
    result = task_decomposer._normalize_supported_retrieval_tasks(
        tasks,
        "比较 RAG 文档切分对 MRR 的影响",
        {"hypotheses": [{"id": "h1", "statement": "重叠切分至少提升 5%"}]},
    )
    for item in result:
        assert "deterministic_lexical_overlap" in item["description"]
        assert "BM25检索器" not in item["description"]
        assert "rank_bm25库" not in item["description"]
        assert "重叠切分至少提升 5%" in item["description"]
    assert "不声称已经运行实验" in result[0]["description"]
    assert "真实 artifact" in result[1]["description"]


def test_contract_references_tolerate_provider_arrays():
    tasks = [{
        "description": "冻结检索实验",
        "task_type": "system_design",
        "hypothesis_id": ["h1", "h2"],
    }]
    result = task_decomposer._normalize_supported_retrieval_tasks(
        tasks,
        "比较 RAG 文档切分对 MRR 的影响",
        {"hypotheses": [{"id": "h1", "statement": "重叠切分提升 MRR"}]},
    )
    assert "重叠切分提升 MRR" in result[0]["description"]
    assert task_decomposer._known_or_default(["h1"], {"h1"}) == "h1"
    assert task_decomposer._known_or_default([], {"h1"}) == "h1"


def test_complete_workflow_adds_only_missing_thesis_roles():
    original = [{
        "title": "设计", "task_type": "system_design",
        "subquestion_id": "sq1", "hypothesis_id": "h1",
    }]
    result = task_decomposer._ensure_complete_workflow(
        original, {"methodology_profile": {"family": "computational"}}, "paper",
    )
    task_types = [item["task_type"] for item in result]

    assert task_types.count("system_design") == 1
    assert task_types.count("literature_survey") == 1
    assert task_types.count("experiment_design") == 1
    assert task_types.count("result_analysis") == 1
    assert task_types.count("report_writing") == 1
    assert all(item.get("subquestion_id") == "sq1" for item in result[1:])


def test_systematic_review_workflow_always_includes_real_study_pool_acquisition():
    result = task_decomposer._ensure_complete_workflow(
        [{"task_type": "literature_survey"}],
        {"methodology_profile": {"family": "systematic_review"}}, "survey",
    )

    assert "data_acquisition" in {item["task_type"] for item in result}


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
    assert "不得覆盖父任务" in context


def test_experiment_protocol_context_is_authoritative():
    context = task_executor._experiment_protocol_context(
        {"method_details": {"retriever": {"type": "deterministic_lexical_overlap"}}}
    )
    assert "权威输入" in context
    assert "deterministic_lexical_overlap" in context
    assert "不得另行编造" in context
    assert "拆解漂移" in context


def test_result_analysis_receives_compact_approved_experiment_metrics():
    run_id = f"run_upstream_{uuid.uuid4().hex[:6]}"
    experiment_task = {
        "id": f"task_exp_{uuid.uuid4().hex[:6]}", "run_id": run_id,
        "title": "实验", "description": "执行", "task_type": "experiment_design",
        "required_skills": {}, "status": "completed", "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    TaskRepository.insert(experiment_task)
    OutputRepository.insert({
        "id": f"out_{experiment_task['id']}", "output_type": "task_result", "title": "实验产出",
        "content": json.dumps({"reproducible_experiment": {
            "summary": "真实实验完成", "publishable": True,
            "claims": [{"statement": "真实实验结论", "provenance": {
                "protocol_id": "protocol_1", "raw_results": "data/results.csv",
                "raw_results_sha256": "a" * 64,
            }}],
            "metrics": {
                "rows": [{"strategy": "no_split", "mrr_at_10": 0.5}],
                "statistical_analysis": {"mean_delta": 0.5, "confidence_interval_95": [0.5, 0.5]},
            },
            "reproduction": {"passed": True},
        }}, ensure_ascii=False),
        "run_id": run_id, "task_id": experiment_task["id"], "agent_id": "grad_experimenter",
        "created_at": datetime.now().isoformat(),
    })
    OutputRepository.insert({
        "id": f"review_{experiment_task['id']}", "output_type": "review", "title": "导师审核",
        "content": json.dumps({"approved": True, "feedback": "通过"}, ensure_ascii=False),
        "run_id": run_id, "task_id": experiment_task["id"], "agent_id": "advisor",
        "created_at": datetime.now().isoformat(),
    })
    context = task_executor._upstream_context({
        "id": "analysis", "run_id": run_id, "task_type": "result_analysis",
    })
    assert "不得声称缺少实验数据" in context
    assert '"mean_delta": 0.5' in context
    assert '"passed": true' in context
    selected = task_executor._approved_task_results(run_id, {"experiment_design"})
    claims = selected["experiment_design"]["reproducible_experiment"]["claims"]
    assert claims[0]["statement"] == "真实实验结论"


def test_result_analysis_accepts_verified_experiment_artifact_provenance():
    gate = scientific_quality_gate_service._provenance_gate(
        {"task_type": "result_analysis"},
        {"claims": [{"statement": "实验结论", "provenance": {
            "protocol_id": "protocol_1", "raw_results": "data/results.csv",
            "raw_results_sha256": "a" * 64,
        }}]},
        {"sources": [], "excerpts": []},
    )
    assert gate["passed"] is True
