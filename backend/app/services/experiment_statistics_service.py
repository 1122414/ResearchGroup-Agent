from __future__ import annotations

import math
import random
import statistics

from ..core.config import settings


class ExperimentStatisticsService:
    def analyze(self, repeat_rows: list[dict], metrics: dict) -> dict:
        deltas = [
            float(item["treatment_value"]) - float(item["baseline_value"])
            for item in repeat_rows
            if item.get("treatment_value") is not None and item.get("baseline_value") is not None
        ]
        repeat_count = len(deltas)
        mean_delta = statistics.mean(deltas) if deltas else 0.0
        std_delta = statistics.stdev(deltas) if repeat_count > 1 else 0.0
        paired_by_metric = metrics.get("paired_query_metric_deltas") or {}
        paired = [float(value) for value in (
            paired_by_metric.get("mrr_at_10") or metrics.get("paired_query_deltas") or []
        )]
        bootstrap_seed = 20260714
        bootstrap_resamples = 1000
        metric_inference = {
            name: self._paired_inference(values, bootstrap_seed, bootstrap_resamples)
            for name, values in sorted(paired_by_metric.items())
            if values
        }
        if paired:
            mrr_inference = metric_inference.get("mrr_at_10") or self._paired_inference(
                paired, bootstrap_seed, bootstrap_resamples
            )
            lower, upper = mrr_inference["confidence_interval_95"]
            mean_delta = mrr_inference["mean_delta"]
            std_delta = mrr_inference["std_delta"]
        else:
            margin = 1.96 * std_delta / math.sqrt(repeat_count) if repeat_count > 1 else 0.0
            lower, upper = mean_delta - margin, mean_delta + margin
        baseline_values = [float(item["baseline_value"]) for item in repeat_rows if item.get("baseline_value") is not None]
        baseline_mean = statistics.mean(baseline_values) if baseline_values else 0.0
        relative_effect = mean_delta / (abs(baseline_mean) + 1e-9)
        strategies = {str(item.get("strategy")) for item in metrics.get("rows") or [] if item.get("strategy")}
        zero_variance = bool(paired) and std_delta == 0
        uniform_note = (
            "全部查询差值相同；冻结数据的 benchmark_design 应说明这是否源于同构边界构造。"
            if zero_variance else "查询级效应存在变异。"
        )
        return {
            "repeat_count": repeat_count,
            "mean_delta": round(mean_delta, 6),
            "std_delta": round(std_delta, 6),
            "confidence_interval_95": [round(lower, 6), round(upper, 6)],
            "relative_effect": round(relative_effect, 6),
            "standardized_effect": round(mean_delta / std_delta, 6) if std_delta else None,
            "standardized_effect_status": (
                "undefined_zero_variance: Cohen's dz has a zero denominator; report raw paired difference and win rate"
                if zero_variance else "estimated"
            ),
            "effect_sizes": {
                "mean_paired_difference": round(mean_delta, 6),
                "relative_effect": round(relative_effect, 6),
                "paired_win_rate": round(sum(value > 0 for value in paired) / len(paired), 6) if paired else None,
                "cohen_dz": round(mean_delta / std_delta, 6) if std_delta else None,
                "cohen_dz_status": "undefined_zero_variance" if zero_variance else "estimated",
            },
            "metric_inference": metric_inference,
            "uniform_effect_diagnostic": uniform_note,
            "evaluation_unit": "query",
            "paired_query_count": len(paired),
            "bootstrap_resamples": bootstrap_resamples if paired else 0,
            "bootstrap_seed": bootstrap_seed if paired else None,
            "execution_seeds": [item.get("seed") for item in repeat_rows],
            "data_split": "frozen evaluation-only benchmark; no fitting or model selection",
            "ablation_present": len(strategies) >= 3,
            "passed": (
                repeat_count >= max(int(settings.experiment_repeat_runs), 2)
                and len(strategies) >= 3
                and (not metrics.get("best_strategy") or len(paired) >= 2)
            ),
        }

    @staticmethod
    def _paired_inference(values: list, seed: int, resamples: int) -> dict:
        paired = [float(value) for value in values]
        rng = random.Random(seed)
        means = sorted(
            statistics.mean(rng.choices(paired, k=len(paired)))
            for _ in range(resamples)
        )
        mean_delta = statistics.mean(paired)
        std_delta = statistics.stdev(paired) if len(paired) > 1 else 0.0
        return {
            "mean_delta": round(mean_delta, 6),
            "std_delta": round(std_delta, 6),
            "confidence_interval_95": [
                round(means[int(resamples * 0.025)], 6),
                round(means[int(resamples * 0.975) - 1], 6),
            ],
            "paired_query_count": len(paired),
            "bootstrap_resamples": resamples,
            "bootstrap_seed": seed,
        }


experiment_statistics_service = ExperimentStatisticsService()
