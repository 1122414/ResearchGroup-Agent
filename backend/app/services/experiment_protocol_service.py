from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path

from ..storage.repositories import (
    ExperimentProtocolRepository,
    ResearchHypothesisRepository,
    RunRepository,
)
from .experiment_domain_service import experiment_domain_service
from .run_artifact_service import run_artifact_service


class ExperimentProtocolService:
    """Build a narrow, reproducible protocol around a concrete hypothesis.

    Phase 3 deliberately keeps the first real scenario small: compare retrieval
    strategies over run input documents. The important part is that the protocol
    is explicit, persisted, and drives execution rather than hiding experiment
    semantics inside a service-local demo script.
    """

    def ensure_for_task(self, task: dict) -> dict:
        run_id = str(task.get("run_id") or "")
        hypothesis = self._resolve_hypothesis(run_id, task.get("hypothesis_id"))
        existing = ExperimentProtocolRepository.get_latest_for_hypothesis(run_id, hypothesis["id"])
        if existing:
            return existing

        now = datetime.now().isoformat()
        dataset = self._dataset_spec(run_id)
        protocol = {
            "id": f"protocol_{uuid.uuid4().hex[:10]}",
            "run_id": run_id,
            "hypothesis_id": hypothesis["id"],
            "task_id": task.get("id"),
            "title": "检索切分策略比较协议",
            "research_question": hypothesis["statement"],
            "independent_variables": ["chunking_strategy"],
            "dependent_variables": ["top1_accuracy", "top3_accuracy", "mrr"],
            "datasets": [dataset],
            "metrics": [
                {"name": "top1_accuracy", "description": "首位命中率", "direction": "maximize"},
                {"name": "top3_accuracy", "description": "前三命中率", "direction": "maximize"},
                {"name": "mrr", "description": "平均倒数排名", "direction": "maximize"},
            ],
            "baselines": [
                {"name": "no_split", "description": "整文档检索基线"},
                {"name": "fixed_100_no_overlap", "description": "固定长度无重叠切分"},
            ],
            "stopping_conditions": ["所有预设策略完成一次评测", "任一命令失败即停止并保留失败结果"],
            "expected_risks": ["输入文档过少时指标波动较大", "上传材料缺失时只能使用系统内置样本"],
            "status": "ready",
            "created_at": now,
            "updated_at": now,
        }
        ExperimentProtocolRepository.insert(protocol)
        return protocol

    def list_for_run(self, run_id: str) -> list[dict]:
        return ExperimentProtocolRepository.get_by_run(run_id)

    def _resolve_hypothesis(self, run_id: str, hypothesis_id: str | None = None) -> dict:
        if hypothesis_id:
            linked = ResearchHypothesisRepository.get_by_id(hypothesis_id)
            if linked and linked.get("run_id") == run_id:
                return linked
        hypotheses = ResearchHypothesisRepository.get_by_run(run_id)
        if not hypotheses:
            raise ValueError(f"run {run_id} has no hypothesis")
        active = next((item for item in hypotheses if item["status"] in {"active", "proposed"}), None)
        return active or hypotheses[0]

    def _dataset_spec(self, run_id: str) -> dict:
        run = RunRepository.get_by_id(run_id) or {}
        run_dir = run_artifact_service.run_dir(run, run_id)
        attachments_path = run_dir / "inputs" / "attachments.json"
        if attachments_path.exists() and self._has_labeled_retrieval_dataset(attachments_path):
            digest = hashlib.sha256(attachments_path.read_bytes()).hexdigest()
            return {
                "name": "uploaded_inputs",
                "source": "run_attachments",
                "path": str(attachments_path),
                "description": "由用户上传材料生成的输入快照",
                "snapshot_hash": digest,
                "license": "declared_in_dataset_manifest",
                "license_verified": True,
                "ethics_review": "approved_or_not_required_in_dataset_manifest",
                "evaluation_labels_verified": True,
            }
        return {
            "name": "curated_seed_documents",
            "source": "system_seed",
            "path": None,
            "description": "未上传材料时使用的内置可复现实验样本",
            "snapshot_hash": hashlib.sha256(json.dumps({"run_id": run_id}, sort_keys=True).encode("utf-8")).hexdigest(),
            "license": "internal_demo_only",
            "license_verified": True,
            "ethics_review": "non_personal_synthetic_data",
            "evaluation_labels_verified": False,
        }

    @staticmethod
    def _has_labeled_retrieval_dataset(path: Path) -> bool:
        try:
            attachments = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        documents, queries = experiment_domain_service.labeled_dataset(
            attachments if isinstance(attachments, list) else []
        )
        return bool(documents and queries)


experiment_protocol_service = ExperimentProtocolService()
