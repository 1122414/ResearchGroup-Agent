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
        if not settings.web_search_enabled:
            return []
        mode = settings.web_search_provider_mode.lower()
        if mode in {"auto", "tavily"} and self._tavily_enabled():
            return self._search_tavily(query)
        return []

    @staticmethod
    def _tavily_enabled() -> bool:
        return bool(settings.web_search_enabled and settings.tavily_api_key)

    def _search_tavily(self, query: str) -> list[dict]:
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
            with urllib.request.urlopen(request, timeout=settings.llm_timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            return []

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
        return normalized


web_search_tool = WebSearchTool()
