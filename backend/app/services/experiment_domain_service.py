from __future__ import annotations

import json
from pathlib import Path

from ..core.research_goal import primary_goal
from ..storage.repositories import ResearchHypothesisRepository
from .run_artifact_service import run_artifact_service


class ExperimentDomainService:
    RETRIEVAL_MARKERS = ("retrieval", "rag", "检索", "召回", "mrr", "问答")

    def classify(self, task: dict, run: dict | None) -> dict:
        hypothesis = ResearchHypothesisRepository.get_by_id(task.get("hypothesis_id")) or {}
        text = " ".join(
            [
                primary_goal(str((run or {}).get("research_goal") or "")),
                str(task.get("title") or ""),
                str(task.get("description") or ""),
                str(hypothesis.get("statement") or ""),
                str(hypothesis.get("primary_metric") or ""),
            ]
        ).lower()
        attachments = self._attachments(task, run)
        documents, queries = self.labeled_dataset(attachments)
        has_labeled_data = bool(documents and queries)
        retrieval = any(marker in text for marker in self.RETRIEVAL_MARKERS)
        if retrieval:
            return {
                "domain": "retrieval_rag",
                "supported": True,
                "publishable_data_ready": has_labeled_data,
                "reason": "matched retrieval capability; publishable execution requires user-supplied documents and labeled queries",
            }
        return {
            "domain": "unsupported",
            "supported": False,
            "publishable_data_ready": False,
            "reason": "当前自动实验仅支持检索/RAG；未将其他课题强行映射为 RAG 实验",
        }

    @staticmethod
    def labeled_dataset(attachments: list[dict]) -> tuple[list[dict], list[dict]]:
        for item in attachments:
            try:
                dataset = json.loads(str(item.get("extracted_markdown") or ""))
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(dataset, dict):
                continue
            if not str(dataset.get("license") or "").strip() or dataset.get("ethics_review") not in {
                "approved", "not_required"
            }:
                continue
            documents = [
                row for row in dataset.get("documents", [])
                if isinstance(row, dict) and row.get("id") and row.get("text")
            ]
            document_ids = {str(row["id"]) for row in documents}
            queries = [
                row for row in dataset.get("queries", [])
                if isinstance(row, dict) and row.get("query") and str(row.get("target_doc")) in document_ids
            ]
            if documents and queries:
                return documents, queries
        return [], []

    @staticmethod
    def _attachments(task: dict, run: dict | None) -> list[dict]:
        if not run:
            return []
        path: Path = run_artifact_service.run_dir(run, task.get("run_id")) / "inputs" / "attachments.json"
        if not path.exists():
            return []
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (json.JSONDecodeError, OSError):
            return []


experiment_domain_service = ExperimentDomainService()
