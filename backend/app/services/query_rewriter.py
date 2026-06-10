from __future__ import annotations

import json
import re

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.logger import logger
from ..core.research_goal import primary_goal

_STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "with", "how",
    "what", "why", "is", "are", "study", "research", "based", "using", "use",
    "调研", "研究", "分析", "如何", "以及", "方法", "一个", "我们", "这个", "进行",
}


class QueryRewriter:
    """Turn a natural-language research goal into precise scholarly queries.

    Revision tasks feed reviewer feedback in so that a retry searches for what
    was missing rather than re-running the identical query and getting the
    identical (insufficient) results.
    """

    async def rewrite(self, goal: str, task: dict | None = None, feedback: str = "") -> list[str]:
        goal = primary_goal(str(goal or "")).strip()
        title = str((task or {}).get("title") or "").strip()
        base = " ".join(item for item in [goal, title] if item).strip()
        limit = max(1, settings.research_agent_max_queries_per_iteration)

        if not settings.research_agent_loop_enabled or settings.mock_mode:
            return self._heuristic(base, feedback, limit)

        try:
            queries = await self._llm_rewrite(base, feedback, limit)
        except Exception as exc:  # noqa: BLE001 - never let query planning break a run
            logger.warning("[QueryRewriter] llm rewrite failed, using heuristic | error=%s", exc)
            queries = []
        queries = [q for q in (queries or []) if q.strip()]
        if not queries:
            queries = self._heuristic(base, feedback, limit)
        return queries[:limit]

    async def _llm_rewrite(self, base: str, feedback: str, limit: int) -> list[str]:
        feedback_block = f"\n上一轮审核反馈（请据此补检索缺口）：{feedback}" if feedback else ""
        prompt = (
            "你是科研检索专家。请把下面的研究目标改写为 "
            f"{limit} 条精确、可直接用于学术检索引擎的查询语句。"
            "优先使用英文术语，覆盖不同子主题、同义表述和方法关键词。"
            f"\n\n研究目标：{base}{feedback_block}\n\n"
            "只返回一个 JSON 字符串数组，不要解释。"
        )
        raw = await create_llm_provider().generate(
            prompt=prompt,
            schema={"type": "array", "items": {"type": "string"}},
            role="advisor_decompose",
        )
        text = raw.strip()
        for fence in ("```json", "```"):
            if text.startswith(fence):
                text = text[len(fence):]
        if text.endswith("```"):
            text = text[:-3]
        parsed = json.loads(text.strip())
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
        return []

    def _heuristic(self, base: str, feedback: str, limit: int) -> list[str]:
        base = base.strip()
        queries: list[str] = []
        if base:
            queries.append(base)
        tokens = [t for t in re.findall(r"[\w\u4e00-\u9fff]+", base) if t.lower() not in _STOPWORDS and len(t) > 1]
        keyword_query = " ".join(tokens[:6]).strip()
        if keyword_query and keyword_query != base:
            queries.append(keyword_query)
        if base:
            queries.append(f"{base} survey")
            queries.append(f"{base} method evaluation")
        if feedback:
            fb_tokens = [t for t in re.findall(r"[\w\u4e00-\u9fff]+", feedback) if t.lower() not in _STOPWORDS and len(t) > 1]
            if fb_tokens:
                queries.append((keyword_query + " " + " ".join(fb_tokens[:4])).strip())
        deduped: list[str] = []
        for query in queries:
            if query and query not in deduped:
                deduped.append(query)
        return deduped[:limit]


query_rewriter = QueryRewriter()
