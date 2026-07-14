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
        if metrics.get("publishable") is False:
            return "实验使用合成演示数据完成，仅证明执行链路可复现，不构成研究结论"
        if metrics.get("best_strategy"):
            best = metrics.get("best_strategy") or {}
            return (
                f"最佳策略={best.get('strategy')}，"
                f"top3_accuracy={best.get('top3_accuracy')}，mrr={best.get('mrr')}"
            )
        if "treatment_value" in metrics and "baseline_value" in metrics:
            return (
                f"{metrics.get('metric_name', 'metric')}: baseline={metrics.get('baseline_value')}, "
                f"treatment={metrics.get('treatment_value')}（方向={metrics.get('direction', 'maximize')}）"
            )
        if "hypothesis_supported" in metrics:
            return str(metrics.get("summary") or ("结果支持假设" if metrics.get("hypothesis_supported") else "结果不支持假设"))
        return "实验完成，但未生成可解释指标"

    @staticmethod
    def _interpret(metrics: dict, status: str) -> tuple[str, float, str]:
        if status != "completed":
            return "inconclusive", settings.experiment_inconclusive_failure_confidence, "实验执行失败，当前结果不足以支持或否定假设"
        if metrics.get("publishable") is False:
            return "inconclusive", 0.0, "实验使用合成演示数据，仅验证执行链路，不能支持或否定研究假设"

        # Legacy retrieval-chunking contract (best_strategy + rows).
        best = metrics.get("best_strategy") or {}
        if best:
            baseline = next((item for item in metrics.get("rows", []) if item.get("strategy") == "no_split"), {})
            best_mrr = float(best.get("mrr") or 0)
            baseline_mrr = float(baseline.get("mrr") or 0)
            statistics_result = metrics.get("statistical_analysis") or {}
            if (
                best_mrr > baseline_mrr
                and float(statistics_result.get("relative_effect") or 0) >= 0.05
                and (statistics_result.get("confidence_interval_95") or [0])[0] > 0
            ):
                return (
                    "supports",
                    round(min(settings.experiment_support_base_confidence + (best_mrr - baseline_mrr), settings.experiment_support_max_confidence), 4),
                    "改进策略优于基线，实验结果支持当前假设",
                )
            if best_mrr >= baseline_mrr:
                return "weakens", settings.experiment_weaken_confidence, "改进未达到预注册最小效应或置信区间仍跨越零"
            return "rejects", settings.experiment_reject_confidence, "改进策略劣于基线，实验结果反驳当前假设"

        # Generic goal-driven contract (baseline_value vs treatment_value).
        if "treatment_value" in metrics and "baseline_value" in metrics:
            return ExperimentResultService._interpret_generic(metrics)

        # Explicit verdict contract.
        if "hypothesis_supported" in metrics:
            if metrics.get("hypothesis_supported"):
                return "supports", settings.experiment_support_base_confidence, str(metrics.get("summary") or "实验结果支持当前假设")
            return "rejects", settings.experiment_reject_confidence, str(metrics.get("summary") or "实验结果反驳当前假设")

        return "inconclusive", settings.experiment_inconclusive_missing_metric_confidence, "实验完成但缺少有效指标"

    @staticmethod
    def _interpret_generic(metrics: dict) -> tuple[str, float, str]:
        try:
            baseline = float(metrics.get("baseline_value"))
            treatment = float(metrics.get("treatment_value"))
        except (TypeError, ValueError):
            return "inconclusive", settings.experiment_inconclusive_missing_metric_confidence, "实验完成但指标无法解析"
        direction = str(metrics.get("direction") or "maximize").lower()
        improved = treatment > baseline if direction == "maximize" else treatment < baseline
        equal = treatment == baseline
        delta = abs(treatment - baseline) / (abs(baseline) + 1e-9)
        metric_name = metrics.get("metric_name", "primary metric")
        if equal:
            return "weakens", settings.experiment_weaken_confidence, f"{metric_name} 与基线持平，未能支持假设"
        if improved:
            confidence = round(min(settings.experiment_support_base_confidence + delta, settings.experiment_support_max_confidence), 4)
            return "supports", confidence, f"{metric_name} 相对基线改进，实验结果支持当前假设"
        return "rejects", settings.experiment_reject_confidence, f"{metric_name} 相对基线变差，实验结果反驳当前假设"


experiment_result_service = ExperimentResultService()
