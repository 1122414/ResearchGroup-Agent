import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from backend.app.core.config import settings
from backend.app.services.artifact_manifest_service import artifact_manifest_service
from backend.app.services.experiment_domain_service import experiment_domain_service
from backend.app.services.experiment_executor import ExperimentExecutorService
from backend.app.services.experiment_statistics_service import experiment_statistics_service
from backend.app.services.independent_reviewer_service import independent_reviewer_service
from backend.app.services.reproducible_experiment_service import reproducible_experiment_service
from backend.app.services.task_executor import task_executor
from backend.app.storage import init_db
from backend.app.storage.repositories import ResearchHypothesisRepository, RunRepository


@pytest.fixture(autouse=True)
def _db():
    init_db()


def test_unsupported_domain_is_not_forced_into_rag():
    result = experiment_domain_service.classify(
        {"title": "蛋白质结构湿实验", "description": "比较培养条件", "run_id": "missing"},
        {"research_goal": "研究不同培养基对细胞生长的影响"},
    )
    assert result["supported"] is False
    assert result["domain"] == "unsupported"


def test_statistics_requires_repeats_and_ablation(monkeypatch):
    monkeypatch.setattr(settings, "experiment_repeat_runs", 3)
    rows = [
        {"baseline_value": 0.5, "treatment_value": 0.6},
        {"baseline_value": 0.5, "treatment_value": 0.62},
        {"baseline_value": 0.5, "treatment_value": 0.61},
    ]
    metrics = {"rows": [{"strategy": "baseline"}, {"strategy": "treatment"}, {"strategy": "ablation"}]}
    result = experiment_statistics_service.analyze(rows, metrics)
    assert result["passed"] is True
    assert result["repeat_count"] == 3
    assert result["relative_effect"] > 0
    assert result["confidence_interval_95"][0] > 0


def test_dataset_requires_license_and_ethics_declaration():
    documents, queries = experiment_domain_service.labeled_dataset(
        [{"extracted_markdown": json.dumps({
            "documents": [{"id": "d1", "text": "content"}],
            "queries": [{"query": "content", "target_doc": "d1"}],
        })}]
    )
    assert documents == []
    assert queries == []


def test_executor_fails_closed_when_sandbox_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.services.experiment_executor.platform.system", lambda: "Linux")
    marker = tmp_path / "must_not_exist"
    result = ExperimentExecutorService()._run_commands(
        tmp_path,
        {"commands": [{"command": f"touch {marker}"}], "env_vars": {}},
    )
    assert result["exit_code"] == 126
    assert result["sandboxed"] is False
    assert not marker.exists()


def test_experiment_narrative_is_derived_from_executed_artifacts():
    result = task_executor._ground_experiment_output({
        "experiment_ran": True,
        "protocol": {
            "id": "protocol_real",
            "research_question": "重叠切分是否优于基线",
            "expected_risks": ["仅限受控 pilot"],
        },
        "metrics": {
            "rows": [
                {"strategy": "no_split", "mrr_at_10": 0.5},
                {"strategy": "fixed_100_overlap_30", "mrr_at_10": 1.0},
            ],
            "statistical_analysis": {
                "mean_delta": 0.5,
                "confidence_interval_95": [0.5, 0.5],
                "bootstrap_resamples": 1000,
                "bootstrap_seed": 20260714,
            },
        },
        "reproduction": {"passed": True},
        "claims": [{"statement": "真实执行结论"}],
        "artifacts": ["data/results.csv"],
        "publishable": True,
    })
    serialized = json.dumps(result, ensure_ascii=False)
    assert "MRR@10=0.5" in result["summary"]
    assert result["findings"]["statistical_analysis"]["bootstrap_resamples"] == 1000
    assert result["claims"] == [{"statement": "真实执行结论"}]
    assert "10000" not in serialized
    assert "种子42" not in serialized


def test_result_analysis_reviewer_uses_artifact_not_literature_passage():
    scope = independent_reviewer_service._result_analysis_review_scope()
    assert "passages 为空是正确的" in scope
    assert "raw_results_sha256" in scope
    assert "逐 query" in scope
    assert "零方差区间可以成立" in scope


def test_report_reviewer_accepts_markdown_findings_and_frozen_protocol():
    scope = independent_reviewer_service._report_writing_review_scope()
    assert "实际论文正文" in scope
    assert "不得在看过结果后擅自增加新基线" in scope
    assert "Cohen's dz 未定义" in scope


@pytest.mark.asyncio
async def test_real_uploaded_retrieval_data_runs_repeats_and_clean_reproduction(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mock_mode", True)
    monkeypatch.setattr(settings, "experiment_execution_enabled", True)
    monkeypatch.setattr(settings, "experiment_execution_backend", "local")
    monkeypatch.setattr(settings, "experiment_require_review", False)
    monkeypatch.setattr(settings, "experiment_generated_code_enabled", False)
    monkeypatch.setattr(settings, "experiment_repeat_runs", 3)
    monkeypatch.setattr(
        ExperimentExecutorService,
        "_sandbox_command",
        staticmethod(lambda command, _workspace: (command, True, True)),
    )

    run_id = f"run_exp_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    artifact_dir = tmp_path / "run"
    (artifact_dir / "inputs").mkdir(parents=True)
    artifact_manifest_service.initialize(artifact_dir, run_id=run_id, display_name="test")
    evaluation_dataset = {
        "license": "user_owned_for_research",
        "ethics_review": "not_required",
        "documents": [
            {"id": "doc_overlap", "text": "重叠切分保留边界上下文并改善检索召回。"},
            {"id": "doc_baseline", "text": "不切分是整文档检索基线，粒度较粗。"},
            {"id": "doc_metrics", "text": "MRR 与 Top-3 Accuracy 衡量检索排序质量。"},
        ],
        "queries": [
            {"query": "重叠切分 边界 上下文", "target_doc": "doc_overlap"},
            {"query": "整文档 检索 基线", "target_doc": "doc_baseline"},
            {"query": "MRR Top-3 排序", "target_doc": "doc_metrics"},
        ],
    }
    (artifact_dir / "inputs" / "attachments.json").write_text(
        json.dumps([{"extracted_markdown": json.dumps(evaluation_dataset, ensure_ascii=False)}], ensure_ascii=False),
        encoding="utf-8",
    )
    run = {
        "id": run_id, "research_goal": "比较 RAG 检索切分策略的 MRR 与召回率", "artifact_dir": str(artifact_dir),
        "status": "executing", "created_at": now, "updated_at": now,
    }
    RunRepository.insert(run)
    hypothesis_id = f"hypothesis_{uuid.uuid4().hex[:8]}"
    ResearchHypothesisRepository.insert(
        {
            "id": hypothesis_id, "run_id": run_id, "statement": "重叠切分的 MRR 优于不切分基线",
            "rationale": "预注册检索比较", "status": "proposed", "confidence": 0,
            "primary_metric": "MRR", "minimum_effect": "5%", "falsification_criterion": "未达到 5%",
            "created_at": now, "updated_at": now,
        }
    )
    task = {
        "id": "task_experiment", "run_id": run_id, "title": "RAG 检索实验", "description": "比较检索策略",
        "hypothesis_id": hypothesis_id, "owner_agent": "grad_experimenter",
    }

    result = await reproducible_experiment_service.run_for_task(task, "grad_experimenter")

    assert result["experiment_ran"] is True, result
    assert result["artifact_class"] == "external"
    assert result["experiment_run"]["dataset_snapshot"]["sha256"]
    assert result["metrics"]["statistical_analysis"]["repeat_count"] == 3
    assert result["metrics"]["statistical_analysis"]["paired_query_count"] == 3
    assert result["metrics"]["statistical_analysis"]["bootstrap_resamples"] == 1000
    assert result["protocol"]["method_details"]["retriever"]["document_aggregation"] == "maximum_chunk_score"
    assert result["protocol"]["method_details"]["retriever"]["top_k"] == [1, 3, 5, 10]
    assert result["protocol"]["metrics"][-2]["name"] == "top5_accuracy"
    assert result["protocol"]["metrics"][-1]["name"] == "mrr_at_10"
    assert result["protocol"]["method_details"]["evaluation_design"]["execution_seeds"] == [1, 2, 3]
    assert "仅作为确定性复现标签" in result["protocol"]["method_details"]["evaluation_design"]["seed_policy"]
    assert result["protocol"]["datasets"][0]["path"] == "inputs/attachments.json"
    assert "不划分训练集" in result["protocol"]["method_details"]["evaluation_design"]["data_split"]
    assert result["protocol"]["method_details"]["evaluation_design"]["reproduction_tolerance"] == 1e-6
    assert "chunk_document" in result["protocol"]["method_details"]["interfaces"]
    assert result["protocol"]["method_details"]["pseudocode"]
    assert "standard library only" in result["protocol"]["method_details"]["execution_environment"]["requirements_content"]
    assert result["preregistration_path"] in result["artifacts"]
    assert any(path.endswith("requirements.txt") for path in result["artifacts"])
    assert any(path.endswith("environment.json") for path in result["artifacts"])
    assert all("top5_accuracy" in row and "mrr_at_10" in row for row in result["metrics"]["rows"])
    assert set(result["metrics"]["statistical_analysis"]["metric_inference"]) == {
        "top1_accuracy", "top3_accuracy", "top5_accuracy", "mrr_at_10",
    }
    assert {
        item["bootstrap_seed"]
        for item in result["metrics"]["statistical_analysis"]["metric_inference"].values()
    } == {20260714}
    assert result["metrics"]["per_query_results"]
    assert result["metrics"]["randomness_audit"]["retrieval_and_metrics"].startswith("deterministic")
    assert result["artifact_hashes"]["data/results.csv"]
    assert result["preregistration_trace"]["sha256"] == result["artifact_hashes"]["preregistration.md"]
    assert "禁止外推至开放域" in result["claims"][0]["statement"]
    assert "query 和文档构造可能导致效应均匀" in result["claims"][0]["statement"]
    assert result["claims"][0]["provenance"]["raw_results_sha256"]
    assert any(path.endswith("hashes.json") for path in result["artifacts"])
    assert "实验预注册" in Path(result["preregistration_path"]).read_text(encoding="utf-8")
    assert result["reproduction"]["passed"] is True
    assert result["publishable"] is True
    reviewer_payload = independent_reviewer_service._compact_experiment(result)
    assert reviewer_payload["metrics"]["statistical_analysis"]["metric_inference"]
    assert reviewer_payload["artifact_hashes"]["data/results.csv"]
    assert reviewer_payload["preregistration_trace"]["protocol_id"] == result["protocol"]["id"]
    assert "per_query_results" not in reviewer_payload["metrics"]
    assert reviewer_payload["per_query_results_summary"]["no_split"]["count"] == 3
    manifest = artifact_manifest_service.read(artifact_dir)
    assert all(item["metadata"].get("sha256") for item in manifest["artifacts"] if item["kind"] == "experiment")
