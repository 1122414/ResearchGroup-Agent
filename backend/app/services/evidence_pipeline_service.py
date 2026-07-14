from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime

from ..core.config import settings
from ..core.research_goal import primary_goal
from ..storage.repositories import (
    EvidenceRepository,
    LiteratureSearchRepository,
    ResearchBriefRepository,
    ResearchMilestoneRepository,
    TaskRepository,
)
from .evidence_provider import evidence_provider
from .browser_research_service import browser_research_service
from .fulltext_ingest_service import fulltext_ingest_service
from .literature_source_service import literature_source_service
from .query_rewriter import query_rewriter
from .run_event_service import run_event_service
from .source_verification_service import source_verification_service

_STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "with",
    "研究", "分析", "调研", "方法", "如何", "以及",
}


class EvidencePipelineService:
    async def collect_for_task(self, task: dict) -> dict:
        query = self._query_for_task(task)
        root_task = self._root_task(task)
        feedback = self._revision_feedback(task)
        if settings.research_agent_loop_enabled:
            queries = await query_rewriter.rewrite(query, root_task, feedback)
        else:
            queries = [self._apply_feedback(query, feedback)] if query else []
        if not queries:
            queries = [query] if query else []

        raw_sources, attempts, browser_count = await self._gather(queries)
        protocol_id = self._record_search_protocol(task, queries, attempts)
        self._record_search_runs(task, protocol_id, attempts)
        self._emit_search_trace(
            task,
            query,
            attempts,
            browser_discovered=browser_count,
            candidate_count=len(raw_sources),
            queries=queries,
        )
        normalized = self._deduplicate_sources([self._normalize_source(source, task) for source in raw_sources])
        normalized = self._rank_by_relevance(normalized, query)
        mode = "remote_provider" if normalized else "curated_fallback"
        if not normalized and settings.literature_curated_fallback_enabled:
            normalized = self._deduplicate_sources(
                [self._normalize_source(source, task) for source in literature_source_service.select_sources(task)]
            )
        if not normalized:
            mode = "no_grounded_source"
        normalized = normalized[: max(settings.evidence_search_max_results, settings.literature_source_limit)]
        before_verification = len(normalized)
        normalized = await browser_research_service.verify_candidates(query, normalized)
        self._emit_verification_trace(task, query, before_verification, normalized)
        if normalized and settings.browser_research_enabled:
            mode = f"{mode}+browser_research"
        if not normalized:
            mode = "no_grounded_source+browser_research" if settings.browser_research_enabled else "no_grounded_source"
        verified = source_verification_service.verify_sources(normalized)
        normalized = [source for source in verified if source_verification_service.citation_eligible(source)]
        self._record_screening(task, verified)
        if not normalized:
            mode = "no_citation_eligible_source"
        persisted = self.persist_sources(task, normalized)
        fulltext_ingested = fulltext_ingest_service.ingest_sources(task.get("run_id"), normalized)
        persisted["excerpts"] = self._content_excerpts(task.get("run_id"), normalized)
        search_metrics = {
            "candidate_count": len(raw_sources),
            "deduplicated_count": before_verification,
            "included_count": len(normalized),
            "duplicate_rate": round(max(len(raw_sources) - before_verification, 0) / max(len(raw_sources), 1), 4),
            "fulltext_acquisition_rate": round(fulltext_ingested / max(len(normalized), 1), 4),
            "passage_count": len(persisted["excerpts"]),
        }
        return {
            "mode": mode,
            "query": query,
            "queries": queries,
            "search_attempts": attempts,
            "fulltext_ingested": fulltext_ingested,
            "search_protocol_id": protocol_id,
            "search_metrics": search_metrics,
            **persisted,
        }

    async def _gather(self, queries: list[str]) -> tuple[list[dict], list[dict], int]:
        sources: list[dict] = []
        attempts: list[dict] = []
        browser_count = 0
        for query in queries:
            if not query:
                continue
            search_result = evidence_provider.search_with_trace(query)
            sources.extend(search_result["results"])
            for item in search_result["attempts"]:
                provider = item.get("provider")
                records = [
                    source
                    for source in search_result["results"]
                    if (source.get("metadata") or {}).get("provider") == provider
                ]
                record_snapshot = json.dumps(records, ensure_ascii=False, sort_keys=True)
                attempts.append(
                    {
                        **item,
                        "query": query,
                        "record_hash": hashlib.sha256(record_snapshot.encode("utf-8")).hexdigest(),
                    }
                )
            browser_sources = await browser_research_service.discover(query)
            sources.extend(browser_sources)
            browser_count += len(browser_sources)
            if settings.browser_research_enabled:
                attempts.append(
                    {"provider": "browser_use", "kind": "browser", "enabled": True,
                     "result_count": len(browser_sources), "error": None, "query": query}
                )
        return sources, attempts, browser_count

    def _record_search_protocol(self, task: dict, queries: list[str], attempts: list[dict]) -> str | None:
        run_id = task.get("run_id")
        if not run_id:
            return None
        now = datetime.now().isoformat()
        protocol_id = f"search_protocol_{uuid.uuid4().hex[:10]}"
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        LiteratureSearchRepository.insert_protocol(
            {
                "id": protocol_id, "run_id": run_id, "task_id": task.get("id"), "version": 1,
                "providers": sorted({str(item.get("provider")) for item in attempts if item.get("provider")}),
                "queries": queries, "languages": ["zh", "en"], "date_range": {},
                "inclusion_criteria": ["与冻结子问题直接相关", "具有可追溯 DOI、URL 或学术库标识"],
                "exclusion_criteria": ["身份无法核验", "与研究范围外事项相关", *(brief.get("scope_out") or [])],
                "status": "frozen", "created_at": now,
            }
        )
        milestone = next(
            (item for item in ResearchMilestoneRepository.get_by_run(run_id) if item["milestone_key"] == "search_protocol_frozen"),
            None,
        )
        if milestone and milestone["status"] == "pending":
            ResearchMilestoneRepository.update(milestone["id"], status="passed", completed_at=now, updated_at=now)
        return protocol_id

    @staticmethod
    def _record_search_runs(task: dict, protocol_id: str | None, attempts: list[dict]) -> None:
        if not protocol_id or not task.get("run_id"):
            return
        now = datetime.now().isoformat()
        for attempt in attempts:
            snapshot = json.dumps(attempt, ensure_ascii=False, sort_keys=True)
            LiteratureSearchRepository.insert_run(
                {
                    "id": f"search_run_{uuid.uuid4().hex[:10]}", "protocol_id": protocol_id,
                    "run_id": task["run_id"], "task_id": task.get("id"), "query": attempt.get("query", ""),
                    "provider": str(attempt.get("provider") or "unknown"),
                    "result_count": int(attempt.get("result_count") or 0), "error": attempt.get("error"),
                    "response_hash": attempt.get("record_hash") or hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
                    "created_at": now,
                }
            )

    @staticmethod
    def _record_screening(task: dict, sources: list[dict]) -> None:
        run_id = task.get("run_id")
        if not run_id:
            return
        now = datetime.now().isoformat()
        for source in sources:
            eligible = source_verification_service.citation_eligible(source)
            status = (source.get("metadata") or {}).get("verification_status", "unverified")
            LiteratureSearchRepository.insert_screening(
                {
                    "id": f"screening_{uuid.uuid4().hex[:10]}", "run_id": run_id,
                    "task_id": task.get("id"), "source_id": source["id"],
                    "decision": "include" if eligible else "exclude",
                    "reason": "identity_verified" if eligible else status, "created_at": now,
                }
            )

    @staticmethod
    def _apply_feedback(query: str, feedback: str) -> str:
        if not feedback:
            return query
        import re

        tokens = [t for t in re.findall(r"[\w\u4e00-\u9fff]+", feedback) if t.lower() not in _STOPWORDS and len(t) > 1]
        extra = " ".join(tokens[:4]).strip()
        return f"{query} {extra}".strip() if extra else query

    @staticmethod
    def _revision_feedback(task: dict) -> str:
        feedback = str(task.get("review_feedback") or task.get("blocked_reason") or "").strip()
        if feedback:
            return feedback
        parent_id = task.get("revision_of_task_id")
        if parent_id:
            parent = TaskRepository.get_by_id(parent_id)
            if parent:
                return str(parent.get("review_feedback") or "").strip()
        return ""

    def _rank_by_relevance(self, sources: list[dict], query: str) -> list[dict]:
        import re

        query_tokens = {t.lower() for t in re.findall(r"[\w\u4e00-\u9fff]+", query) if t.lower() not in _STOPWORDS}
        if not query_tokens:
            return sources

        def score(source: dict) -> float:
            metadata = source.get("metadata", {}) or {}
            text = " ".join(
                str(part)
                for part in [
                    source.get("title"),
                    source.get("venue"),
                    metadata.get("summary"),
                    metadata.get("content"),
                ]
                if part
            ).lower()
            source_tokens = {t for t in re.findall(r"[\w\u4e00-\u9fff]+", text)}
            if not source_tokens:
                return 0.0
            return len(query_tokens & source_tokens) / (len(query_tokens) ** 0.5)

        return [source for _, source in sorted(enumerate(sources), key=lambda pair: (-score(pair[1]), pair[0]))]

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
        normalized = source_verification_service.verify_sources(normalized)
        normalized = [source for source in normalized if source_verification_service.citation_eligible(source)]
        persisted = self.persist_sources({"run_id": run_id, "id": None}, normalized)
        fulltext_ingest_service.ingest_sources(run_id, normalized)
        persisted["excerpts"] = self._content_excerpts(run_id, normalized)
        return {"query": query, "search_attempts": search_result["attempts"], **persisted}

    @staticmethod
    def _content_excerpts(run_id: str | None, sources: list[dict]) -> list[dict]:
        if not run_id:
            return []
        source_ids = {source["id"] for source in sources}
        return [
            excerpt
            for excerpt in EvidenceRepository.get_by_run(run_id)["excerpts"]
            if excerpt["source_id"] in source_ids
            and excerpt.get("excerpt_type") not in {"metadata_only", "summary"}
            and str(excerpt.get("excerpt") or "").strip()
        ]

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
    def _root_task(task: dict) -> dict:
        root_task = task
        visited: set[str] = set()
        while root_task.get("revision_of_task_id") and root_task["id"] not in visited:
            visited.add(root_task["id"])
            parent = TaskRepository.get_by_id(root_task["revision_of_task_id"])
            if not parent:
                break
            root_task = parent
        return root_task

    def _query_for_task(self, task: dict) -> str:
        root_task = self._root_task(task)
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
    def _emit_search_trace(
        task: dict,
        query: str,
        attempts: list[dict],
        browser_discovered: int,
        candidate_count: int,
        queries: list[str] | None = None,
    ) -> None:
        run_id = task.get("run_id")
        if not run_id:
            return
        query_list = queries or [query]
        run_event_service.emit(
            run_id,
            "evidence.search.completed",
            "evidence",
            "完成多源文献检索",
            f"围绕原始课题用 {len(query_list)} 条检索式完成检索，候选来源 {candidate_count} 条。",
            task_id=task.get("id"),
            payload={
                "query": query,
                "queries": query_list,
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
        excerpt_type = "visible_text"
        if not text:
            methods = metadata.get("methods") or []
            method_text = ", ".join(methods) if methods else "bibliographic metadata only"
            text = f"{source['title']} | methods: {method_text}"
            excerpt_type = "metadata_only"
        text = re.sub(r"\s+", " ", text).strip()[: settings.evidence_excerpt_max_chars]
        return {
            "id": f"excerpt_{uuid.uuid4().hex[:10]}",
            "run_id": run_id,
            "source_id": source["id"],
            "excerpt": text,
            "locator": source.get("url") or "",
            "excerpt_type": excerpt_type,
            "captured_at": now,
        }

    @staticmethod
    def _deduplicate_sources(sources: list[dict]) -> list[dict]:
        seen: set[str] = set()
        deduped: list[dict] = []
        for source in sources:
            metadata = source.get("metadata") or {}
            canonical = metadata.get("canonical_id") or metadata.get("openalex_id") or metadata.get("paper_id")
            title = re.sub(r"\W+", " ", str(source.get("title") or "").lower()).strip()
            authors = re.sub(r"\W+", " ", str(source.get("authors") or "").lower()).strip()
            key = str(source.get("doi") or canonical or source.get("url") or f"{title}|{authors[:80]}").strip().lower()
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
