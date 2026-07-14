from __future__ import annotations

import math
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
        margin = 1.96 * std_delta / math.sqrt(repeat_count) if repeat_count > 1 else 0.0
        baseline_values = [float(item["baseline_value"]) for item in repeat_rows if item.get("baseline_value") is not None]
        baseline_mean = statistics.mean(baseline_values) if baseline_values else 0.0
        relative_effect = mean_delta / (abs(baseline_mean) + 1e-9)
        strategies = {str(item.get("strategy")) for item in metrics.get("rows") or [] if item.get("strategy")}
        return {
            "repeat_count": repeat_count,
            "mean_delta": round(mean_delta, 6),
            "std_delta": round(std_delta, 6),
            "confidence_interval_95": [round(mean_delta - margin, 6), round(mean_delta + margin, 6)],
            "relative_effect": round(relative_effect, 6),
            "standardized_effect": round(mean_delta / std_delta, 6) if std_delta else None,
            "ablation_present": len(strategies) >= 3,
            "passed": repeat_count >= max(int(settings.experiment_repeat_runs), 2) and len(strategies) >= 3,
        }


experiment_statistics_service = ExperimentStatisticsService()
