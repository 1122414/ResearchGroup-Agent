from __future__ import annotations

import json
import os
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
        limited = sources[: settings.browser_use_max_candidates]
        try:
            history = await self._run_agent(
                task=self._verification_task(query, limited),
                output_model=BrowserVerificationResult,
            )
            parsed = self._structured_output(history, BrowserVerificationResult)
        except Exception as exc:
            logger.warning("[BrowserResearch] verify failed | error=%s", exc)
            return [] if settings.browser_verification_required else sources

        verdicts = parsed.verdicts if parsed else []
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
        return verified

    async def _run_agent(self, task: str, output_model: type[BaseModel]):
        Agent, Browser, llm = self._load_runtime()
        browser = Browser(headless=settings.browser_use_headless)
        agent = Agent(task=task, llm=llm, browser=browser, output_model_schema=output_model)
        try:
            return await agent.run(max_steps=settings.browser_use_max_steps)
        finally:
            close = getattr(browser, "close", None)
            if close:
                result = close()
                if hasattr(result, "__await__"):
                    await result

    @staticmethod
    def _structured_output(history, output_model: type[BaseModel]):
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
        return output_model.model_validate_json(final_result)

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
            )
        return Agent, Browser, llm

    @staticmethod
    def _discovery_task(query: str) -> str:
        return f"""
你是文献调研网页发现器。只围绕研究课题检索，不得扩写结论。

任务：
1. 围绕 query 检索外部网页与论文落地页：{query}
2. 优先返回论文页、DOI 页、出版社页、官方项目页。
3. 最多返回 {settings.browser_use_max_candidates} 个候选来源。
4. 每个来源必须给出真实 URL；找不到就不要返回。
5. evidence 只写页面上可见的核验片段，不要根据记忆补充。
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
你是文献来源网页核验器，只负责验证，不负责补写结论。

研究 query：{query}
候选来源：
{json.dumps(compact, ensure_ascii=False, indent=2)}

要求：
1. 只打开候选来源给出的 URL，不要扩展到无关网页。
2. 逐条核验页面标题与 DOI 是否匹配。
3. accepted=true 只能用于页面可直接支持的候选来源。
4. evidence 只记录页面可见证据；不确定时 accepted=false。
5. verdicts 的 url 必须和候选来源 url 完全一致。
"""


browser_research_service = BrowserResearchService()
