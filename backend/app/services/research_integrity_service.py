from __future__ import annotations

import json
import re

from ..core.config import settings


class ResearchIntegrityService:
    """Keep literature outputs grounded in verified sources only."""

    def render_allowed_sources(self, sources: list[dict]) -> str:
        if not sources:
            return "[]"
        compact = [
            {
                "source_id": item["id"],
                "title": item.get("title", ""),
                "authors": item.get("authors", ""),
                "year": item.get("year"),
                "venue": item.get("venue", ""),
                "doi": item.get("doi"),
                "url": item.get("url"),
            }
            for item in sources
        ]
        return json.dumps(compact, ensure_ascii=False, indent=2)

    def apply_literature_policy(self, result: dict, sources: list[dict], query: str, source_mode: str) -> dict:
        allowed_ids = {item["id"] for item in sources}
        allowed_urls = {str(item.get("url") or "").strip() for item in sources if item.get("url")}
        allowed_dois = {str(item.get("doi") or "").strip().lower() for item in sources if item.get("doi")}

        if settings.literature_require_grounded_sources and len(sources) < settings.literature_min_grounded_sources:
            return self._insufficient_evidence_result(query, source_mode, sources)

        references_used = result.get("references_used") or []
        if not isinstance(references_used, list):
            references_used = []
        normalized_refs = [str(item) for item in references_used]

        violations: list[str] = []
        unknown_refs = sorted(set(normalized_refs) - allowed_ids)
        if unknown_refs:
            violations.append(f"unknown source ids: {', '.join(unknown_refs)}")

        serialized = json.dumps(result, ensure_ascii=False)
        bracket_refs = set(re.findall(r"\[(source_[^\]\s]+)\]", serialized))
        unknown_bracket_refs = sorted(bracket_refs - allowed_ids)
        if unknown_bracket_refs:
            violations.append(f"unknown bracket citations: {', '.join(unknown_bracket_refs)}")

        cited_urls = {item.rstrip('",.。；;') for item in re.findall(r"https?://[^\s\]）)]+", serialized)}
        unknown_urls = sorted(item for item in cited_urls if item not in allowed_urls)
        if unknown_urls:
            violations.append(f"unknown urls: {', '.join(unknown_urls)}")

        cited_dois = {
            item.lower()
            for item in re.findall(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", serialized, flags=re.IGNORECASE)
        }
        unknown_dois = sorted(item for item in cited_dois if item not in allowed_dois)
        if unknown_dois:
            violations.append(f"unknown dois: {', '.join(unknown_dois)}")

        if settings.citation_validation_enabled and violations:
            return self._blocked_fabrication_result(query, source_mode, sources, violations)

        grounded = dict(result)
        grounded["references_used"] = [item for item in normalized_refs if item in allowed_ids]
        grounded["grounded_source_ids"] = [item["id"] for item in sources]
        grounded["academic_integrity"] = {
            "status": "passed",
            "query": query,
            "source_mode": source_mode,
            "allowed_source_count": len(sources),
            "violations": [],
        }
        return grounded

    @staticmethod
    def _insufficient_evidence_result(query: str, source_mode: str, sources: list[dict]) -> dict:
        return {
            "summary": "未检索到足够的可核验来源，系统拒绝生成未经证实的参考文献或结论。",
            "findings": [],
            "deliverables": ["已完成面向研究课题的证据检索，但当前证据不足"],
            "risks": ["缺少足够的可核验来源，当前不宜形成文献结论"],
            "next_steps": ["扩大检索范围、补充关键词或上传已知文献后再继续归纳"],
            "references_used": [],
            "grounded_source_ids": [item["id"] for item in sources],
            "insufficient_evidence": True,
            "academic_integrity": {
                "status": "insufficient_evidence",
                "query": query,
                "source_mode": source_mode,
                "allowed_source_count": len(sources),
                "violations": [],
            },
        }

    @staticmethod
    def _blocked_fabrication_result(query: str, source_mode: str, sources: list[dict], violations: list[str]) -> dict:
        return {
            "summary": "检测到未在证据白名单中的引用，系统已拦截该输出，避免产生不可核验的学术内容。",
            "findings": [],
            "deliverables": ["已保留可核验来源，未采纳存在引用违规的生成内容"],
            "risks": ["原始输出包含未授权引用，已被系统拒绝"],
            "next_steps": ["仅基于允许来源重新归纳，或先补充更多真实证据"],
            "references_used": [],
            "grounded_source_ids": [item["id"] for item in sources],
            "integrity_blocked": True,
            "academic_integrity": {
                "status": "blocked_fabrication",
                "query": query,
                "source_mode": source_mode,
                "allowed_source_count": len(sources),
                "violations": violations,
            },
        }


research_integrity_service = ResearchIntegrityService()
