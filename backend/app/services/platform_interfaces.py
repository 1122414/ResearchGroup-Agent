from __future__ import annotations


class DatasetProvider:
    """Reserved extension point for future dataset sources."""

    def resolve(self, spec: dict) -> dict:
        raise NotImplementedError("DatasetProvider is reserved for future integrations")


class MetricEvaluator:
    """Reserved extension point for pluggable metric execution."""

    def evaluate(self, result: dict, metric_spec: dict) -> dict:
        raise NotImplementedError("MetricEvaluator is reserved for future integrations")


class ExecutionSandbox:
    """Reserved extension point for docker / remote / queue execution."""

    def run(self, plan: dict) -> dict:
        raise NotImplementedError("ExecutionSandbox is reserved for future integrations")


class NotebookExporter:
    """Reserved extension point for reportable notebook artifacts."""

    def export(self, experiment_result: dict) -> str:
        raise NotImplementedError("NotebookExporter is reserved for future integrations")


class ResultVisualizer:
    """Reserved extension point for future chart renderers."""

    def render(self, experiment_result: dict) -> list[str]:
        raise NotImplementedError("ResultVisualizer is reserved for future integrations")
