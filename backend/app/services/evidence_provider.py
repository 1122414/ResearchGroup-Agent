from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from ..core.config import settings
from .browser_research_service import browser_research_service
from .web_search_tool import web_search_tool


class EvidenceProvider:
    def list_capabilities(self) -> list[dict]:
        return [
            {"name": "local_attachment", "enabled": True},
            {"name": "manual_metadata", "enabled": True},
            *web_search_tool.list_capabilities(),
            *browser_research_service.list_capabilities(),
            {"name": "crossref", "enabled": self._crossref_enabled()},
            {"name": "arxiv", "enabled": False},
            {"name": "semantic_scholar", "enabled": False},
            {"name": "zotero", "enabled": False},
        ]

    def search(self, query: str) -> list[dict]:
        mode = settings.evidence_provider_mode.lower()
        if mode == "tavily":
            return web_search_tool.search(query)
        if mode == "crossref":
            return self._search_crossref(query) if self._crossref_enabled() else []
        if mode == "auto":
            results: list[dict] = []
            results.extend(web_search_tool.search(query))
            if self._crossref_enabled():
                results.extend(self._search_crossref(query))
            return results
        return []

    def register_source(self, source: dict) -> dict:
        return source

    def resolve_source(self, source_id: str) -> dict | None:
        return None

    @staticmethod
    def _crossref_enabled() -> bool:
        return bool(settings.evidence_remote_search_enabled and settings.crossref_enabled)

    def _search_crossref(self, query: str) -> list[dict]:
        params = {
            "query": query,
            "rows": settings.evidence_search_max_results,
        }
        if settings.crossref_mailto:
            params["mailto"] = settings.crossref_mailto
        request = urllib.request.Request(
            f"{settings.crossref_base_url.rstrip('/')}/works?{urllib.parse.urlencode(params)}",
            headers={"User-Agent": self._crossref_user_agent()},
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.llm_timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            return []

        normalized: list[dict] = []
        for item in body.get("message", {}).get("items", [])[: settings.evidence_search_max_results]:
            authors = ", ".join(
                " ".join(part for part in [author.get("given", ""), author.get("family", "")] if part).strip()
                for author in item.get("author", [])[:5]
            )
            published_parts = (
                item.get("published-print", {}).get("date-parts")
                or item.get("published-online", {}).get("date-parts")
                or item.get("issued", {}).get("date-parts")
                or []
            )
            year = published_parts[0][0] if published_parts and published_parts[0] else None
            normalized.append(
                {
                    "id": item.get("DOI") or "",
                    "title": (item.get("title") or ["untitled source"])[0],
                    "authors": authors,
                    "year": year,
                    "venue": (item.get("container-title") or [""])[0],
                    "doi": item.get("DOI"),
                    "url": item.get("URL"),
                    "source_type": "paper",
                    "metadata": {
                        "provider": "crossref",
                        "type": item.get("type"),
                        "is_referenced_by_count": item.get("is-referenced-by-count"),
                    },
                }
            )
        return normalized

    @staticmethod
    def _crossref_user_agent() -> str:
        if settings.crossref_mailto:
            return f"ResearchGroup-Agent/1.0 (mailto:{settings.crossref_mailto})"
        return "ResearchGroup-Agent/1.0"


evidence_provider = EvidenceProvider()
