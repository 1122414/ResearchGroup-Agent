from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..core.config import settings


class WebSearchTool:
    """Extensible network-search tool boundary.

    Tavily is the first concrete provider. Future providers can be added here
    without changing the evidence pipeline or graduate-agent execution flow.
    """

    def list_capabilities(self) -> list[dict]:
        return [
            {
                "name": "tavily",
                "kind": "web_search",
                "enabled": self._tavily_enabled(),
            }
        ]

    def search(self, query: str) -> list[dict]:
        return self.search_with_trace(query)["results"]

    def search_with_trace(self, query: str) -> dict:
        if not settings.web_search_enabled:
            return {"results": [], "attempts": [self._attempt("tavily", False, 0, "web_search_disabled")]}
        mode = settings.web_search_provider_mode.lower()
        if mode in {"auto", "tavily"} and self._tavily_enabled():
            results, error = self._search_tavily(query)
            return {"results": results, "attempts": [self._attempt("tavily", True, len(results), error)]}
        return {"results": [], "attempts": [self._attempt("tavily", False, 0, "provider_disabled_or_unconfigured")]}

    @staticmethod
    def _tavily_enabled() -> bool:
        return bool(settings.web_search_enabled and settings.tavily_api_key)

    def _search_tavily(self, query: str) -> tuple[list[dict], str | None]:
        payload = json.dumps(
            {
                "api_key": settings.tavily_api_key,
                "query": query,
                "search_depth": settings.tavily_search_depth,
                "max_results": settings.evidence_search_max_results,
                "include_answer": False,
                "include_raw_content": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{settings.tavily_base_url.rstrip('/')}/search",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.evidence_search_timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            return [], exc.__class__.__name__

        normalized: list[dict] = []
        for item in body.get("results", [])[: settings.evidence_search_max_results]:
            normalized.append(
                {
                    "id": "",
                    "title": item.get("title") or item.get("url") or "untitled source",
                    "authors": "",
                    "year": None,
                    "venue": "",
                    "doi": None,
                    "url": item.get("url"),
                    "source_type": "web",
                    "metadata": {
                        "provider": "tavily",
                        "score": item.get("score"),
                        "content": item.get("content") or "",
                    },
                }
            )
        return normalized, None

    @staticmethod
    def _attempt(provider: str, enabled: bool, result_count: int, error: str | None = None) -> dict:
        return {
            "provider": provider,
            "kind": "web_search",
            "enabled": enabled,
            "result_count": result_count,
            "error": error,
        }


web_search_tool = WebSearchTool()
