from __future__ import annotations

import re
import uuid
from datetime import datetime

from ..core.config import settings
from ..core.research_goal import primary_goal
from ..storage.repositories import EvidenceRepository, TaskRepository
from .evidence_provider import evidence_provider
from .browser_research_service import browser_research_service
from .literature_source_service import literature_source_service
from .run_event_service import run_event_service


class EvidencePipelineService:
    async def collect_for_task(self, task: dict) -> dict:
        query = self._query_for_task(task)
        search_result = evidence_provider.search_with_trace(query)
        sources = list(search_result["results"])
        browser_sources = await browser_research_service.discover(query)
        sources.extend(browser_sources)
        self._emit_search_trace(
            task,
            query,
            search_result["attempts"],
            browser_discovered=len(browser_sources),
            candidate_count=len(sources),
        )
        mode = "remote_provider" if sources else "curated_fallback"
        if not sources:
            sources = literature_source_service.select_sources(task)
        if not sources:
            mode = "no_grounded_source"
        normalized = self._deduplicate_sources([self._normalize_source(source, task) for source in sources])
        before_verification = len(normalized)
        normalized = await browser_research_service.verify_candidates(query, normalized)
        self._emit_verification_trace(task, query, before_verification, normalized)
        if sources and settings.browser_research_enabled:
            mode = f"{mode}+browser_research"
        if not normalized:
            mode = "no_grounded_source+browser_research" if settings.browser_research_enabled else "no_grounded_source"
        persisted = self.persist_sources(task, normalized)
        return {"mode": mode, "query": query, "search_attempts": search_result["attempts"], **persisted}

    async def collect_for_query(self, run_id: str, query: str) -> dict:
        search_result = evidence_provider.search_with_trace(query)
        raw_sources = list(search_result["results"])
        browser_sources = await browser_research_service.discover(query)
        raw_sources.extend(browser_sources)
        self._emit_search_trace(
            {"run_id": run_id, "id": None},
            query,
            search_result["attempts"],
            browser_discovered=len(browser_sources),
            candidate_count=len(raw_sources),
        )
        normalized = self._deduplicate_sources([self._normalize_source(source, {"id": None}) for source in raw_sources])
        before_verification = len(normalized)
        normalized = await browser_research_service.verify_candidates(query, normalized)
        self._emit_verification_trace({"run_id": run_id, "id": None}, query, before_verification, normalized)
        persisted = self.persist_sources({"run_id": run_id, "id": None}, normalized)
        return {"query": query, "search_attempts": search_result["attempts"], **persisted}

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
        root_task = task
        visited: set[str] = set()
        while root_task.get("revision_of_task_id") and root_task["id"] not in visited:
            visited.add(root_task["id"])
            parent = TaskRepository.get_by_id(root_task["revision_of_task_id"])
            if not parent:
                break
            root_task = parent
        return " ".join(
            item
            for item in [
                primary_goal(str(root_task.get("description") or "")),
                str(root_task.get("title") or ""),
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

    @staticmethod
    def _emit_search_trace(task: dict, query: str, attempts: list[dict], browser_discovered: int, candidate_count: int) -> None:
        run_id = task.get("run_id")
        if not run_id:
            return
        run_event_service.emit(
            run_id,
            "evidence.search.completed",
            "evidence",
            "完成多源文献检索",
            f"围绕原始课题完成检索，候选来源 {candidate_count} 条。",
            task_id=task.get("id"),
            payload={
                "query": query,
                "attempts": attempts,
                "browser_discovered": browser_discovered,
                "candidate_count": candidate_count,
            },
        )

    @staticmethod
    def _emit_verification_trace(task: dict, query: str, candidate_count: int, verified_sources: list[dict]) -> None:
        run_id = task.get("run_id")
        if not run_id:
            return
        rejected = max(candidate_count - len(verified_sources), 0)
        run_event_service.emit(
            run_id,
            "evidence.verification.completed",
            "evidence",
            "完成来源核验",
            f"候选来源 {candidate_count} 条，保留 {len(verified_sources)} 条，剔除 {rejected} 条。",
            task_id=task.get("id"),
            payload={
                "query": query,
                "candidate_count": candidate_count,
                "accepted_count": len(verified_sources),
                "rejected_count": rejected,
            },
        )

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
