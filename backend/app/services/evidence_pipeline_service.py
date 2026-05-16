from __future__ import annotations

import re
import uuid
from datetime import datetime

from ..core.config import settings
from ..core.research_goal import primary_goal
from ..storage.repositories import EvidenceRepository
from .evidence_provider import evidence_provider
from .literature_source_service import literature_source_service


class EvidencePipelineService:
    def collect_for_task(self, task: dict) -> dict:
        query = self._query_for_task(task)
        sources = evidence_provider.search(query)
        mode = "remote_provider" if sources else "curated_fallback"
        if not sources:
            sources = literature_source_service.select_sources(task)
        normalized = self._deduplicate_sources([self._normalize_source(source, task) for source in sources])
        persisted = self.persist_sources(task, normalized)
        return {"mode": mode, "query": query, **persisted}

    def collect_for_query(self, run_id: str, query: str) -> dict:
        raw_sources = evidence_provider.search(query)
        normalized = self._deduplicate_sources([self._normalize_source(source, {"id": None}) for source in raw_sources])
        persisted = self.persist_sources({"run_id": run_id, "id": None}, normalized)
        return {"query": query, **persisted}

    def persist_sources(self, task: dict, sources: list[dict]) -> dict:
        run_id = task.get("run_id")
        now = datetime.now().isoformat()
        excerpts: list[dict] = []
        assessments: list[dict] = []
        if not run_id:
            return {"sources": sources, "excerpts": excerpts, "assessments": assessments}
        for source in sources:
            EvidenceRepository.upsert_source(
                {
                    "id": source["id"],
                    "run_id": run_id,
                    "task_id": task.get("id"),
                    "title": source["title"],
                    "authors": source.get("authors", ""),
                    "year": source.get("year"),
                    "venue": source.get("venue", ""),
                    "doi": source.get("doi"),
                    "url": source.get("url"),
                    "source_type": source.get("source_type", "paper"),
                    "metadata": source.get("metadata", {}),
                    "created_at": now,
                }
            )
            excerpt = self._build_excerpt(run_id, source, now)
            assessment = self._build_assessment(run_id, source, excerpt["id"], now)
            EvidenceRepository.insert_excerpt(excerpt)
            EvidenceRepository.insert_assessment(assessment)
            excerpts.append(excerpt)
            assessments.append(assessment)
        return {"sources": sources, "excerpts": excerpts, "assessments": assessments}

    @staticmethod
    def _query_for_task(task: dict) -> str:
        return " ".join(
            item
            for item in [
                primary_goal(str(task.get("description") or "")),
                str(task.get("title") or ""),
            ]
            if item
        ).strip()

    def _normalize_source(self, source: dict, task: dict) -> dict:
        raw_id = source.get("id") or ""
        source_id = f"source_{uuid.uuid4().hex[:10]}"
        metadata = dict(source.get("metadata") or {})
        if raw_id:
            metadata.setdefault("canonical_id", raw_id)
        if source.get("methods"):
            metadata.setdefault("methods", source.get("methods", []))
        metadata.setdefault("query_task_id", task.get("id"))
        return {
            "id": source_id,
            "title": source.get("title") or "untitled source",
            "authors": source.get("authors", ""),
            "year": source.get("year"),
            "venue": source.get("venue", ""),
            "doi": source.get("doi"),
            "url": source.get("url"),
            "source_type": source.get("source_type", "paper"),
            "methods": source.get("methods", metadata.get("methods", [])),
            "metadata": metadata,
        }

    def _build_excerpt(self, run_id: str, source: dict, now: str) -> dict:
        metadata = source.get("metadata", {})
        text = str(metadata.get("content") or "")
        if not text:
            methods = metadata.get("methods") or []
            method_text = ", ".join(methods) if methods else "bibliographic metadata only"
            text = f"{source['title']} | methods: {method_text}"
        text = re.sub(r"\s+", " ", text).strip()[: settings.evidence_excerpt_max_chars]
        return {
            "id": f"excerpt_{uuid.uuid4().hex[:10]}",
            "run_id": run_id,
            "source_id": source["id"],
            "excerpt": text,
            "locator": source.get("url") or "",
            "excerpt_type": "summary",
            "captured_at": now,
        }

    @staticmethod
    def _deduplicate_sources(sources: list[dict]) -> list[dict]:
        seen: set[str] = set()
        deduped: list[dict] = []
        for source in sources:
            key = str(source.get("url") or source.get("doi") or source.get("title") or "").strip().lower()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            deduped.append(source)
        return deduped

    def _build_assessment(self, run_id: str, source: dict, excerpt_id: str, now: str) -> dict:
        year = source.get("year")
        freshness = 1.0
        if isinstance(year, int):
            age = max(datetime.now().year - year, 0)
            freshness = max(0.0, 1 - age / max(settings.evidence_stale_after_years, 1))
        is_primary = source.get("source_type") in {"paper", "dataset", "experiment"}
        is_peer_reviewed = bool(source.get("venue")) and source.get("source_type") == "paper"
        relevance = 1.0
        credibility = 0.5
        if is_primary:
            credibility += settings.evidence_primary_source_bonus
        if is_peer_reviewed:
            credibility += settings.evidence_peer_review_bonus
        overall = round(min((relevance + credibility + freshness) / 3, 1.0), 4)
        return {
            "id": f"assessment_{uuid.uuid4().hex[:10]}",
            "run_id": run_id,
            "source_id": source["id"],
            "excerpt_id": excerpt_id,
            "relevance_score": relevance,
            "credibility_score": round(min(credibility, 1.0), 4),
            "freshness_score": round(freshness, 4),
            "conflict_score": 0.0,
            "overall_score": overall,
            "is_primary": is_primary,
            "is_peer_reviewed": is_peer_reviewed,
            "notes": "automated heuristic assessment",
            "created_at": now,
        }


evidence_pipeline_service = EvidencePipelineService()
