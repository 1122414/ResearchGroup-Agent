import json
import uuid
from datetime import datetime

import pytest

from backend.app.core.config import settings
from backend.app.services.artifact_manifest_service import artifact_manifest_service
from backend.app.services.experiment_domain_service import experiment_domain_service
from backend.app.services.experiment_executor import ExperimentExecutorService
from backend.app.services.experiment_statistics_service import experiment_statistics_service
from backend.app.services.reproducible_experiment_service import reproducible_experiment_service
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
    assert result["reproduction"]["passed"] is True
    assert result["publishable"] is True
    manifest = artifact_manifest_service.read(artifact_dir)
    assert all(item["metadata"].get("sha256") for item in manifest["artifacts"] if item["kind"] == "experiment")
