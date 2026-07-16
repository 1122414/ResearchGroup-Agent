from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..core.config import settings
from ..core.logger import logger


class BrowserDiscoveredSource(BaseModel):
    title: str = ""
    authors: str = ""
    year: int | None = None
    venue: str = ""
    doi: str | None = None
    url: str | None = None
    source_type: str = "webpage"
    evidence: str = ""


class BrowserDiscoveryResult(BaseModel):
    sources: list[BrowserDiscoveredSource] = Field(default_factory=list)


class BrowserVerificationRecord(BaseModel):
    url: str | None = None
    accepted: bool = False
    title_match: bool = False
    doi_match: bool = False
    evidence: str = ""
    reject_reason: str = ""


class BrowserVerificationResult(BaseModel):
    verdicts: list[BrowserVerificationRecord] = Field(default_factory=list)


class BrowserResearchService:
    def list_capabilities(self) -> list[dict]:
        return [
            {
                "name": "browser_use",
                "kind": "browser_research",
                "enabled": self.enabled(),
                "verification_enabled": settings.browser_verification_enabled,
            }
        ]

    @staticmethod
    def enabled() -> bool:
        return bool(settings.browser_research_enabled and settings.browser_research_provider_mode == "browser_use")

    async def discover(self, query: str) -> list[dict]:
        if not self.enabled():
            return []
        try:
            history = await self._run_agent(
                task=self._discovery_task(query),
                output_model=BrowserDiscoveryResult,
            )
            if self._judge_rejected(history):
                logger.warning("[BrowserResearch] discover rejected by independent browser judge")
                return []
            parsed = self._structured_output(history, BrowserDiscoveryResult)
        except Exception as exc:
            logger.warning("[BrowserResearch] discover failed | error=%s", exc)
            return []

        if not parsed:
            return []
        results: list[dict] = []
        for item in parsed.sources[: settings.browser_use_max_candidates]:
            if not item.url:
                continue
            results.append(
                {
                    "id": item.doi or item.url,
                    "title": item.title or "untitled browser source",
                    "authors": item.authors,
                    "year": item.year,
                    "venue": item.venue,
                    "doi": item.doi,
                    "url": item.url,
                    "source_type": item.source_type or "webpage",
                    "metadata": {
                        "provider": "browser_use",
                        "content": item.evidence,
                        "discovery_mode": "browser",
                    },
                }
            )
        return results

    async def verify_candidates(self, query: str, sources: list[dict]) -> list[dict]:
        if not settings.browser_verification_enabled or not self.enabled() or not sources:
            return sources
        limited = self._verification_candidates(sources)
        if not limited:
            return self._verification_error_fallback(sources, "no_verification_candidates")
        limited_urls = {str(source.get("url") or "").strip() for source in limited if source.get("url")}
        try:
            history = await self._run_agent(
                task=self._verification_task(query, limited),
                output_model=BrowserVerificationResult,
            )
            if self._judge_rejected(history):
                logger.warning("[BrowserResearch] verification rejected by independent browser judge")
                limited_ids = {id(source) for source in limited}
                return [source for source in sources if id(source) not in limited_ids]
            parsed = self._structured_output(history, BrowserVerificationResult)
        except Exception as exc:
            logger.warning("[BrowserResearch] verify failed | error=%s", exc)
            return self._verification_error_fallback(sources, str(exc))

        verdicts = parsed.verdicts if parsed else []
        if settings.browser_verification_required and not verdicts:
            return self._verification_error_fallback(sources, "missing_verdicts")
        by_url = {str(item.url or "").strip(): item for item in verdicts if item.url}
        verified: list[dict] = []
        for source in sources:
            url = str(source.get("url") or "").strip()
            verdict = by_url.get(url)
            metadata = dict(source.get("metadata") or {})
            metadata["browser_verification"] = (
                verdict.model_dump() if verdict else {"accepted": False, "reject_reason": "missing_verdict"}
            )
            enriched = {**source, "metadata": metadata}
            if verdict and verdict.accepted:
                verified.append(enriched)
            elif not settings.browser_verification_required:
                verified.append(enriched)
            elif self._can_keep_without_browser_acceptance(source, verdict, url in limited_urls):
                metadata["browser_verification"] = self._fallback_verification_record(source, verdict, url in limited_urls)
                verified.append({**source, "metadata": metadata})
        return verified

    @staticmethod
    def _verification_candidates(sources: list[dict]) -> list[dict]:
        limit = max(int(settings.browser_use_max_candidates), 0)
        if not limit:
            return []

        def priority(source: dict) -> tuple[int, str]:
            metadata = source.get("metadata") or {}
            provider = metadata.get("provider")
            if provider == "browser_use":
                return (0, str(source.get("title") or ""))
            if BrowserResearchService._is_trusted_metadata_source(source):
                return (1, str(source.get("title") or ""))
            return (2, str(source.get("title") or ""))

        # Structured scholarly providers already supply stable identifiers and
        # are verified again by SourceVerificationService. Sending them through
        # an autonomous browser adds latency and repeated-tab failure modes
        # without strengthening citation identity.
        untrusted = [
            source for source in sources
            if not BrowserResearchService._is_trusted_metadata_source(source)
            and not BrowserResearchService._is_integrity_verified_attachment(source)
        ]
        return sorted(untrusted, key=priority)[:limit]

    @staticmethod
    def _can_keep_without_browser_acceptance(source: dict, verdict: BrowserVerificationRecord | None, was_verification_candidate: bool) -> bool:
        if not BrowserResearchService._is_fallback_eligible_source(source):
            return False
        if not was_verification_candidate:
            return True
        if verdict is None:
            return True
        return not verdict.reject_reason and not verdict.evidence

    @staticmethod
    def _is_trusted_metadata_source(source: dict) -> bool:
        metadata = source.get("metadata") or {}
        provider = metadata.get("provider")
        has_traceable_id = bool(source.get("doi") or source.get("url"))
        direct_arxiv = bool(re.match(
            r"https?://(?:www\.)?arxiv\.org/(?:abs|html|pdf)/\d{4}\.\d{4,5}(?:v\d+)?(?:\.pdf)?(?:[?#].*)?$",
            str(source.get("url") or "").strip(),
            re.IGNORECASE,
        ))
        return bool(
            direct_arxiv or (
                source.get("source_type") == "paper"
                and provider in {"crossref", "openalex", "arxiv", "semantic_scholar"}
                and has_traceable_id
            )
        )

    @staticmethod
    def _is_search_metadata_source(source: dict) -> bool:
        metadata = source.get("metadata") or {}
        provider = metadata.get("provider")
        return bool(
            source.get("url")
            and source.get("title")
            and (provider in {"tavily", "browser_use"} or source.get("source_type") in {"web", "webpage"})
        )

    @staticmethod
    def _is_integrity_verified_attachment(source: dict) -> bool:
        metadata = source.get("metadata") or {}
        return bool(
            metadata.get("origin") == "user_attachment"
            and metadata.get("attachment_integrity_verified")
            and metadata.get("content_hash")
            and source.get("url")
        )

    @staticmethod
    def _is_fallback_eligible_source(source: dict) -> bool:
        return (
            BrowserResearchService._is_integrity_verified_attachment(source)
            or BrowserResearchService._is_trusted_metadata_source(source)
            or BrowserResearchService._is_search_metadata_source(source)
        )

    @staticmethod
    def _fallback_verification_record(
        source: dict,
        verdict: BrowserVerificationRecord | None = None,
        was_verification_candidate: bool = False,
        error: str | None = None,
    ) -> dict:
        record = verdict.model_dump() if verdict else {}
        record.update(
            {
                "accepted": True,
                "fallback": (
                    "trusted_scholarly_metadata"
                    if BrowserResearchService._is_trusted_metadata_source(source)
                    else "search_result_metadata"
                ),
                "verification_candidate": was_verification_candidate,
            }
        )
        if error:
            record["error"] = error[:300]
        metadata = source.get("metadata") or {}
        if metadata.get("provider"):
            record["provider"] = metadata["provider"]
        return record

    @staticmethod
    def _verification_error_fallback(sources: list[dict], error: str) -> list[dict]:
        """Avoid throwing away strong scholarly metadata when the browser agent itself fails."""
        if not settings.browser_verification_required:
            return sources
        fallback: list[dict] = []
        for source in sources:
            if BrowserResearchService._is_fallback_eligible_source(source):
                metadata = dict(source.get("metadata") or {})
                metadata["browser_verification"] = BrowserResearchService._fallback_verification_record(source, error=error)
                fallback.append({**source, "metadata": metadata})
        return fallback

    async def _run_agent(self, task: str, output_model: type[BaseModel]):
        Agent, Browser, llm = self._load_runtime()
        schema_text = json.dumps(output_model.model_json_schema(), ensure_ascii=False, indent=2)
        task_with_schema = (
            f"{task}\n\n"
            f"You MUST return your final answer as a JSON object matching this schema:\n"
            f"{schema_text}\n"
        )
        browser = Browser(headless=settings.browser_use_headless)
        agent = Agent(
            task=task_with_schema,
            llm=llm,
            browser=browser,
            output_model_schema=output_model,
        )
        try:
            return await agent.run(max_steps=settings.browser_use_max_steps)
        finally:
            close = getattr(browser, "close", None)
            if close:
                result = close()
                if hasattr(result, "__await__"):
                    await result

    @staticmethod
    def _judge_rejected(history) -> bool:
        checker = getattr(history, "is_validated", None)
        if not callable(checker):
            return False
        try:
            return checker() is False
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _structured_output(history, output_model: type[BaseModel]):
        import re

        structured = getattr(history, "structured_output", None)
        if structured is not None:
            if isinstance(structured, output_model):
                return structured
            return output_model.model_validate(structured)
        getter = getattr(history, "get_structured_output", None)
        if getter:
            return getter(output_model)
        final_result = getattr(history, "final_result", lambda: None)()
        if not final_result:
            return None
        try:
            return output_model.model_validate_json(final_result)
        except Exception:
            pass
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", final_result, re.DOTALL)
        if m:
            try:
                return output_model.model_validate_json(m.group(1).strip())
            except Exception:
                pass
        start = final_result.find("{")
        end = final_result.rfind("}")
        if start != -1 and end > start:
            try:
                return output_model.model_validate_json(final_result[start : end + 1])
            except Exception:
                pass
        return None

    @staticmethod
    def _load_runtime():
        config_dir = Path(settings.browser_use_config_dir)
        if not config_dir.is_absolute():
            config_dir = settings.artifacts_dir.parent / config_dir
        os.environ.setdefault("BROWSER_USE_CONFIG_DIR", str(config_dir))
        try:
            from browser_use import Agent, Browser, ChatBrowserUse, ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("browser-use 未安装，请先安装 backend requirements") from exc

        provider: Literal["browser_use", "openai_compatible"] = (
            "browser_use" if settings.browser_use_model_provider == "browser_use" else "openai_compatible"
        )
        if provider == "browser_use":
            llm = ChatBrowserUse()
        else:
            llm = ChatOpenAI(
                model=settings.browser_use_model_name or settings.graduate_model_name or settings.llm_model_name,
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                # Many OpenAI-compatible gateways reject the `response_format`
                # parameter ("This response_format type is unavailable now").
                # Tell browser-use to express the schema via the system prompt
                # instead of forcing structured output through the API.
                dont_force_structured_output=True,
                add_schema_to_system_prompt=True,
            )
        return Agent, Browser, llm

    @staticmethod
    def _discovery_task(query: str) -> str:
        return f"""
Find verifiable academic or authoritative web sources for this research query:
{query}

Instructions:
1. If the query contains priority candidate URLs, open those directly before using a search engine; otherwise use web search and open result pages when needed.
2. Prefer academic metadata pages, publisher pages, DOI pages, arXiv, OpenAlex, Crossref, Semantic Scholar, official government or official venue pages.
3. Return at most {settings.browser_use_max_candidates} sources.
4. Each source must include a real URL that can be opened again.
5. Do not invent authors, years, DOI values, or URLs.
6. The evidence field must contain only short text that was visible on the page or in the search result.
"""

    @staticmethod
    def _verification_task(query: str, sources: list[dict]) -> str:
        compact = [
            {
                "title": item.get("title"),
                "doi": item.get("doi"),
                "url": item.get("url"),
            }
            for item in sources
        ]
        return f"""
Verify only the bibliographic identity of these candidate sources.

Candidate sources:
{json.dumps(compact, ensure_ascii=False, indent=2)}

Instructions:
1. Open each URL.
2. Accept a source only when the opened page confirms the title and, when provided, the DOI.
3. Use accepted=true only if the page visibly supports the candidate metadata.
4. evidence must contain the visible page text that supports the decision.
5. If the page cannot be opened, the title does not match, or the evidence is unclear, set accepted=false and write a reject_reason.
6. Return one verdict per candidate URL.
7. Do not research, summarize, or search the article body for topical claims or metrics.
8. Visit each URL at most once. As soon as all URLs have a metadata verdict, call done with the required JSON object.
"""


browser_research_service = BrowserResearchService()
