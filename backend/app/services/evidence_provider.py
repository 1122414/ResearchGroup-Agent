from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

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
            {"name": "openalex", "enabled": self._openalex_enabled()},
            {"name": "arxiv", "enabled": self._arxiv_enabled()},
            {"name": "semantic_scholar", "enabled": self._semantic_scholar_enabled()},
            {"name": "zotero", "enabled": False},
        ]

    def search(self, query: str) -> list[dict]:
        return self.search_with_trace(query)["results"]

    def search_with_trace(self, query: str) -> dict:
        mode = settings.evidence_provider_mode.lower()
        if mode == "tavily":
            return web_search_tool.search_with_trace(query)
        if mode == "crossref":
            return self._single_provider_result("crossref", self._crossref_enabled(), self._search_crossref, query)
        if mode == "openalex":
            return self._single_provider_result("openalex", self._openalex_enabled(), self._search_openalex, query)
        if mode == "arxiv":
            return self._single_provider_result("arxiv", self._arxiv_enabled(), self._search_arxiv, query)
        if mode == "semantic_scholar":
            return self._single_provider_result(
                "semantic_scholar",
                self._semantic_scholar_enabled(),
                self._search_semantic_scholar,
                query,
            )
        if mode == "auto":
            results: list[dict] = []
            attempts: list[dict] = []
            web = web_search_tool.search_with_trace(query)
            results.extend(web["results"])
            attempts.extend(web["attempts"])
            for provider, enabled, searcher in [
                ("crossref", self._crossref_enabled(), self._search_crossref),
                ("openalex", self._openalex_enabled(), self._search_openalex),
                ("arxiv", self._arxiv_enabled(), self._search_arxiv),
                ("semantic_scholar", self._semantic_scholar_enabled(), self._search_semantic_scholar),
            ]:
                provider_result = self._single_provider_result(provider, enabled, searcher, query)
                results.extend(provider_result["results"])
                attempts.extend(provider_result["attempts"])
            return {"results": results, "attempts": attempts}
        return {"results": [], "attempts": [self._attempt(mode or "unknown", False, 0, "unsupported_mode")]}

    def register_source(self, source: dict) -> dict:
        return source

    def resolve_source(self, source_id: str) -> dict | None:
        return None

    @staticmethod
    def _crossref_enabled() -> bool:
        return bool(settings.evidence_remote_search_enabled and settings.crossref_enabled)

    @staticmethod
    def _openalex_enabled() -> bool:
        return bool(settings.evidence_remote_search_enabled and settings.openalex_enabled)

    @staticmethod
    def _arxiv_enabled() -> bool:
        return bool(settings.evidence_remote_search_enabled and settings.arxiv_enabled)

    @staticmethod
    def _semantic_scholar_enabled() -> bool:
        return bool(settings.evidence_remote_search_enabled and settings.semantic_scholar_enabled)

    def _search_crossref(self, query: str) -> tuple[list[dict], str | None]:
        result_limit = max(int(settings.evidence_search_max_results), 1)
        params = {
            "query.bibliographic": self._scholarly_query(query),
            "rows": min(max(result_limit * 4, 20), 100),
        }
        if settings.crossref_mailto:
            params["mailto"] = settings.crossref_mailto
        request = urllib.request.Request(
            f"{settings.crossref_base_url.rstrip('/')}/works?{urllib.parse.urlencode(params)}",
            headers={"User-Agent": self._crossref_user_agent()},
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.evidence_search_timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            return [], exc.__class__.__name__

        normalized: list[dict] = []
        for item in body.get("message", {}).get("items", []):
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
            landing_url = item.get("URL")
            links = [link for link in item.get("link") or [] if str(link.get("URL") or "").startswith("http")]
            fulltext_link = next(
                (link for link in links if "pdf" in str(link.get("content-type") or "").lower()),
                links[0] if links else None,
            )
            fulltext_url = (fulltext_link or {}).get("URL")
            normalized.append(
                {
                    "id": item.get("DOI") or "",
                    "title": (item.get("title") or ["untitled source"])[0],
                    "authors": authors,
                    "year": year,
                    "venue": (item.get("container-title") or [""])[0],
                    "doi": item.get("DOI"),
                    "url": fulltext_url or landing_url,
                    "source_type": "paper",
                    "metadata": {
                        "provider": "crossref",
                        "type": item.get("type"),
                        "is_referenced_by_count": item.get("is-referenced-by-count"),
                        "landing_page_url": landing_url,
                        "fulltext_url": fulltext_url,
                    },
                }
            )
        low_value_types = {"component", "reference-entry", "peer-review"}
        substantive = [
            item for item in normalized
            if (item.get("metadata") or {}).get("type") not in low_value_types
        ]
        secondary = [item for item in normalized if item not in substantive]
        return [*substantive, *secondary][:result_limit], None

    @staticmethod
    def _scholarly_query(query: str, max_terms: int = 16) -> str:
        """Keep provider queries concise; Crossref handles concepts better than Boolean prose."""
        ignored = {
            "and", "or", "not", "the", "a", "an", "of", "for", "to", "in", "on",
            "with", "by", "from", "as", "at", "is", "are", "be", "how", "does",
            "this", "that", "these", "those", "study", "research", "analysis", "evidence", "review",
            "reported", "frozen", "snapshot", "differ", "produce", "complete", "dissertation",
            "within", "contract", "attached", "data",
            "percentage", "percent", "share", "versus", "vs", "between", "country",
            "countries", "economy", "economies", "group", "groups", "comparative",
            "comparison", "cross-country", "descriptive", "statistics", "statistical",
            "high-income", "low-income", "middle-income", "lower-middle-income",
            "upper-middle-income",
        }
        terms: list[str] = []
        seen: set[str] = set()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]+|[\u4e00-\u9fff]{2,}", str(query or "")):
            key = token.lower()
            if key in ignored or key in seen:
                continue
            seen.add(key)
            terms.append(token)
            if len(terms) >= max_terms:
                break
        return " ".join(terms) or str(query or "")[:240]

    def _search_openalex(self, query: str) -> tuple[list[dict], str | None]:
        params = {
            "search": self._scholarly_query(query),
            "per-page": settings.evidence_search_max_results,
        }
        if settings.openalex_mailto:
            params["mailto"] = settings.openalex_mailto
        request = urllib.request.Request(
            f"{settings.openalex_base_url.rstrip('/')}/works?{urllib.parse.urlencode(params)}",
            headers={"User-Agent": self._crossref_user_agent()},
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.evidence_search_timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            return [], exc.__class__.__name__

        normalized: list[dict] = []
        for item in body.get("results", [])[: settings.evidence_search_max_results]:
            authors = ", ".join(
                str(authorship.get("author", {}).get("display_name") or "").strip()
                for authorship in item.get("authorships", [])[:5]
                if authorship.get("author", {}).get("display_name")
            )
            primary_location = item.get("primary_location") or {}
            best_oa_location = item.get("best_oa_location") or {}
            source = (best_oa_location.get("source") or primary_location.get("source") or {})
            fulltext_url = best_oa_location.get("pdf_url") or primary_location.get("pdf_url")
            landing_url = (
                best_oa_location.get("landing_page_url")
                or primary_location.get("landing_page_url")
                or item.get("doi")
                or item.get("id")
            )
            normalized.append(
                {
                    "id": self._normalize_doi(item.get("doi")) or item.get("id") or "",
                    "title": item.get("display_name") or "untitled source",
                    "authors": authors,
                    "year": item.get("publication_year"),
                    "venue": source.get("display_name") or "",
                    "doi": self._normalize_doi(item.get("doi")),
                    "url": fulltext_url or landing_url,
                    "source_type": "paper",
                    "metadata": {
                        "provider": "openalex",
                        "openalex_id": item.get("id"),
                        "cited_by_count": item.get("cited_by_count"),
                        "type": item.get("type"),
                        "landing_page_url": landing_url,
                        "fulltext_url": fulltext_url,
                    },
                }
            )
        return normalized, None

    def _search_arxiv(self, query: str) -> tuple[list[dict], str | None]:
        params = {
            "search_query": f"all:{self._scholarly_query(query)}",
            "start": 0,
            "max_results": settings.evidence_search_max_results,
        }
        request = urllib.request.Request(
            f"{settings.arxiv_base_url.rstrip('/')}/query?{urllib.parse.urlencode(params)}",
            headers={"User-Agent": "ResearchGroup-Agent/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.evidence_search_timeout_seconds) as response:
                body = response.read()
            root = ET.fromstring(body)
        except (urllib.error.URLError, ET.ParseError, TimeoutError) as exc:
            return [], exc.__class__.__name__

        atom = {"atom": "http://www.w3.org/2005/Atom"}
        normalized: list[dict] = []
        for entry in root.findall("atom:entry", atom)[: settings.evidence_search_max_results]:
            raw_id = (entry.findtext("atom:id", default="", namespaces=atom) or "").strip()
            title = " ".join((entry.findtext("atom:title", default="", namespaces=atom) or "").split())
            published = (entry.findtext("atom:published", default="", namespaces=atom) or "").strip()
            year = int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else None
            authors = ", ".join(
                author.findtext("atom:name", default="", namespaces=atom) or ""
                for author in entry.findall("atom:author", atom)[:5]
            )
            normalized.append(
                {
                    "id": raw_id or title,
                    "title": title or "untitled source",
                    "authors": authors,
                    "year": year,
                    "venue": "arXiv",
                    "doi": None,
                    "url": raw_id,
                    "source_type": "paper",
                    "metadata": {
                        "provider": "arxiv",
                        "summary": " ".join((entry.findtext("atom:summary", default="", namespaces=atom) or "").split()),
                    },
                }
            )
        return normalized, None

    def _search_semantic_scholar(self, query: str) -> tuple[list[dict], str | None]:
        params = {
            "query": self._scholarly_query(query),
            "limit": settings.evidence_search_max_results,
            "fields": "paperId,title,authors,year,venue,url,externalIds",
        }
        headers = {"User-Agent": "ResearchGroup-Agent/1.0"}
        if settings.semantic_scholar_api_key:
            headers["x-api-key"] = settings.semantic_scholar_api_key
        request = urllib.request.Request(
            f"{settings.semantic_scholar_base_url.rstrip('/')}/paper/search?{urllib.parse.urlencode(params)}",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.evidence_search_timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            return [], exc.__class__.__name__

        normalized: list[dict] = []
        for item in body.get("data", [])[: settings.evidence_search_max_results]:
            external_ids = item.get("externalIds") or {}
            doi = external_ids.get("DOI")
            normalized.append(
                {
                    "id": doi or item.get("paperId") or "",
                    "title": item.get("title") or "untitled source",
                    "authors": ", ".join(author.get("name", "") for author in item.get("authors", [])[:5]),
                    "year": item.get("year"),
                    "venue": item.get("venue") or "",
                    "doi": doi,
                    "url": item.get("url"),
                    "source_type": "paper",
                    "metadata": {
                        "provider": "semantic_scholar",
                        "paper_id": item.get("paperId"),
                    },
                }
            )
        return normalized, None

    def _single_provider_result(self, provider: str, enabled: bool, searcher, query: str) -> dict:
        if not enabled:
            return {"results": [], "attempts": [self._attempt(provider, False, 0, "provider_disabled_or_unconfigured")]}
        results, error = searcher(query)
        return {"results": results, "attempts": [self._attempt(provider, True, len(results), error)]}

    @staticmethod
    def _attempt(provider: str, enabled: bool, result_count: int, error: str | None = None) -> dict:
        return {
            "provider": provider,
            "kind": "evidence_provider",
            "enabled": enabled,
            "result_count": result_count,
            "error": error,
        }

    @staticmethod
    def _normalize_doi(value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.strip()
        for prefix in ("https://doi.org/", "http://doi.org/"):
            if normalized.lower().startswith(prefix):
                return normalized[len(prefix):]
        return normalized

    @staticmethod
    def _crossref_user_agent() -> str:
        if settings.crossref_mailto:
            return f"ResearchGroup-Agent/1.0 (mailto:{settings.crossref_mailto})"
        return "ResearchGroup-Agent/1.0"


evidence_provider = EvidenceProvider()
