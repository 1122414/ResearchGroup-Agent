from __future__ import annotations

import uuid
from datetime import datetime

from ..core.config import settings
from ..storage.repositories import (
    ExperimentFindingRepository,
    ExperimentResultRepository,
    ResearchClaimRepository,
    ResearchHypothesisRepository,
)
from .claim_evaluation_service import claim_evaluation_service


class ExperimentResultService:
    def record(
        self,
        *,
        protocol: dict,
        experiment_run: dict,
        status: str,
        result: dict,
        metrics: dict,
        artifacts: list[str],
    ) -> dict:
        now = datetime.now().isoformat()
        result_item = {
            "id": f"exp_result_{uuid.uuid4().hex[:10]}",
            "experiment_run_id": experiment_run["id"],
            "protocol_id": protocol["id"],
            "run_id": protocol["run_id"],
            "status": status,
            "summary": self._summary(status, metrics, result),
            "metrics": metrics,
            "exit_code": result.get("exit_code"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "artifacts": artifacts,
            "created_at": now,
        }
        ExperimentResultRepository.insert(result_item)
        finding = self._record_finding(protocol, experiment_run, result_item, metrics)
        return {"result": result_item, "finding": finding}

    def _record_finding(self, protocol: dict, experiment_run: dict, result_item: dict, metrics: dict) -> dict:
        hypothesis = ResearchHypothesisRepository.get_by_id(protocol["hypothesis_id"])
        claims = ResearchClaimRepository.get_by_run(protocol["run_id"])
        related_claim = next((item for item in claims if item.get("hypothesis_id") == protocol["hypothesis_id"]), None)

        relation_type, confidence, statement = self._interpret(metrics, result_item["status"])
        finding = {
            "id": f"finding_{uuid.uuid4().hex[:10]}",
            "protocol_id": protocol["id"],
            "experiment_run_id": experiment_run["id"],
            "result_id": result_item["id"],
            "run_id": protocol["run_id"],
            "hypothesis_id": protocol["hypothesis_id"],
            "claim_id": related_claim["id"] if related_claim else None,
            "relation_type": relation_type,
            "statement": statement,
            "confidence": confidence,
            "created_at": datetime.now().isoformat(),
        }
        ExperimentFindingRepository.insert(finding)

        if hypothesis:
            hypothesis_status = {
                "supports": "supported",
                "weakens": "revised",
                "rejects": "rejected",
                "inconclusive": "active",
            }[relation_type]
            ResearchHypothesisRepository.update(
                hypothesis["id"],
                status=hypothesis_status,
                confidence=confidence,
                updated_at=datetime.now().isoformat(),
            )

        if related_claim:
            claim_evaluation_service.evaluate(related_claim["id"])
        return finding

    @staticmethod
    def _summary(status: str, metrics: dict, result: dict) -> str:
        if status != "completed":
            return f"实验失败，退出码={result.get('exit_code')}"
        best = metrics.get("best_strategy") or {}
        if not best:
            return "实验完成，但未生成可解释指标"
        return (
            f"最佳策略={best.get('strategy')}，"
            f"top3_accuracy={best.get('top3_accuracy')}，mrr={best.get('mrr')}"
        )

    @staticmethod
    def _interpret(metrics: dict, status: str) -> tuple[str, float, str]:
        if status != "completed":
            return "inconclusive", settings.experiment_inconclusive_failure_confidence, "实验执行失败，当前结果不足以支持或否定假设"
        best = metrics.get("best_strategy") or {}
        if not best:
            return "inconclusive", settings.experiment_inconclusive_missing_metric_confidence, "实验完成但缺少有效指标"

        baseline = next((item for item in metrics.get("rows", []) if item.get("strategy") == "no_split"), {})
        best_mrr = float(best.get("mrr") or 0)
        baseline_mrr = float(baseline.get("mrr") or 0)
        if best_mrr > baseline_mrr:
            return (
                "supports",
                round(min(settings.experiment_support_base_confidence + (best_mrr - baseline_mrr), settings.experiment_support_max_confidence), 4),
                "改进策略优于基线，实验结果支持当前假设",
            )
        if best_mrr == baseline_mrr:
            return "weakens", settings.experiment_weaken_confidence, "改进策略未优于基线，实验结果削弱当前假设"
        return "rejects", settings.experiment_reject_confidence, "改进策略劣于基线，实验结果反驳当前假设"


experiment_result_service = ExperimentResultService()
