from __future__ import annotations

import hashlib
import json
import platform
import uuid
from datetime import datetime
from pathlib import Path

from ..core.config import settings
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
            "dependent_variables": [
                "top1_accuracy", "top3_accuracy", "top5_accuracy", "mrr_at_10",
            ],
            "datasets": [dataset],
            "metrics": [
                {"name": "top1_accuracy", "description": "首位命中率", "direction": "maximize"},
                {"name": "top3_accuracy", "description": "前三命中率", "direction": "maximize"},
                {"name": "top5_accuracy", "description": "前五命中率", "direction": "maximize"},
                {"name": "mrr_at_10", "description": "截断至排名 10 的平均倒数排名（MRR@10）", "direction": "maximize"},
            ],
            "baselines": [
                {"name": "no_split", "description": "整文档检索主基线；其余检索与评估设置完全相同"},
                {"name": "fixed_100_no_overlap", "description": "100 字符固定窗口、0 字符重叠消融基线"},
            ],
            "method_details": {
                "strategies": {
                    "no_split": {"chunk_size": None, "overlap": 0},
                    "fixed_100_no_overlap": {"chunk_size": 100, "overlap": 0},
                    "fixed_100_overlap_30": {"chunk_size": 100, "overlap": 30},
                },
                "retriever": {
                    "type": "deterministic_lexical_overlap",
                    "tokenizer": "lowercase_unicode_word_regex",
                    "score": "|query_tokens intersect chunk_tokens| / sqrt(|query_tokens| * |chunk_tokens|)",
                    "document_aggregation": "maximum_chunk_score",
                    "top_k": [1, 3, 5, 10],
                    "embedding_model": None,
                    "rationale": (
                        "使用无拟合参数、可逐项解释且跨运行确定的词法重叠检索器，"
                        "用于隔离切分边界这一自变量；本 pilot 不比较检索器能力，也不外推到 BM25 或语义检索。"
                    ),
                },
                "comparison_policy": "所有策略共享数据、query/qrel、检索器、聚合和评测代码，仅改变切分策略",
                "evaluation_design": {
                    "unit": "query",
                    "query_count": "由冻结上传快照决定",
                    "data_split": "不划分训练集；该确定性检索器无拟合或调参过程，全部冻结 query 仅用于一次评估",
                    "resampling": "对 query/qrel 对进行有放回配对 bootstrap 1000 次",
                    "bootstrap_seed": 20260714,
                    "execution_seeds": [1, 2, 3],
                    "seed_policy": (
                        "三个执行种子仅作为确定性复现标签；每次均在完整冻结 query/qrel 上评估，不再次抽样。"
                        "全部执行完成后，独立使用 bootstrap_seed=20260714 对原始 query 级配对差值做 1000 次有放回 bootstrap。"
                    ),
                    "confidence_level": 0.95,
                    "reproduction_tolerance": settings.experiment_reproduction_tolerance,
                },
                "interfaces": {
                    "chunk_document": "chunk_document(text: str, strategy: str) -> list[str]",
                    "score": "score(query: str, chunk: str) -> float",
                    "evaluate": "evaluate(chunks: list[dict], queries: list[dict]) -> dict[str, float]",
                    "paired_bootstrap": (
                        "paired_bootstrap(deltas: list[float], seed: int, resamples: int = 1000) "
                        "-> tuple[float, float]"
                    ),
                },
                "pseudocode": [
                    "读取并校验冻结数据快照哈希，构造 documents 与 query/qrel。",
                    "对每种 strategy 切分全部文档；其余检索和评估设置保持不变。",
                    "计算 query 与 chunk 的词法重叠分数，并以最大 chunk 分数聚合到文档。",
                    "按分数降序和 document_id 升序稳定排序，计算 Top-1/3/5 与 MRR@10。",
                    "三个执行标签分别运行完整冻结数据，并保存逐 query 结果。",
                    "用 bootstrap_seed 对 treatment-baseline 查询级差值配对重采样 1000 次。",
                    "在干净目录复现并逐项比较主指标，绝对差不得超过冻结容差。",
                ],
                "execution_environment": {
                    "python": platform.python_version(),
                    "implementation": platform.python_implementation(),
                    "required_third_party_packages": [],
                    "requirements_path": "requirements.txt",
                    "requirements_content": "# Core experiment uses Python standard library only.\n",
                    "environment_manifest_path": "environment.json",
                    "note": "核心检索、评估与统计仅依赖 Python 标准库；绘图为可选产物，不参与指标或通过判定。",
                },
                "scope": "受控边界检索 pilot；不得外推到开放域、自然语言真实语料或其他检索器",
            },
            "stopping_conditions": [
                "三个固定执行种子全部完成；任一命令失败即停止并保留失败结果",
                "查询级配对 bootstrap 达到 1000 次并输出 95% 区间",
                f"干净目录复现主指标绝对差异不超过 {settings.experiment_reproduction_tolerance:g}",
            ],
            "expected_risks": [
                "小样本风险：40 文档、20 query 的统计功效和外部效度有限；缓解：报告配对效应量、95% 区间并禁止开放域外推",
                "指标饱和风险：受控词项可能使 Top-k 饱和；缓解：同时报告 MRR@10、逐 query 差值与原始结果，不选择性隐藏指标",
                "内置样本风险：上传材料缺失时只能运行系统样本；缓解：强制标记为不可发布，不能形成经验结论",
                "语义破坏风险：固定字符边界可能破坏语义；缓解：所有组共享检索器和评估器，结论仅限冻结边界 pilot",
            ],
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
                "path": "inputs/attachments.json",
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
            "path": "system_seed/curated_seed_documents.json",
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
