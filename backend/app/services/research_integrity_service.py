from __future__ import annotations

import json
import re

from ..core.config import settings


class ResearchIntegrityService:
    """Keep literature outputs grounded in verified sources only."""

    ACADEMIC_MARKERS = (
        "literature review",
        "systematic review",
        "survey paper",
        "paper",
        "doi",
        "citation",
        "reference",
        "references",
        "文献",
        "论文",
        "综述",
        "引用",
        "参考文献",
        "学术",
    )

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

    def apply_literature_policy(
        self,
        result: dict,
        sources: list[dict],
        query: str,
        source_mode: str,
        task: dict | None = None,
    ) -> dict:
        required_source_count = self.required_grounded_source_count(task, query)
        if settings.literature_require_grounded_sources and len(sources) < required_source_count:
            return self._insufficient_evidence_result(query, source_mode, sources, required_source_count)

        allowed_ids = {item["id"] for item in sources}
        violations = self._citation_violations(result, sources, allowed_ids)
        if settings.citation_validation_enabled and violations:
            return self._blocked_fabrication_result(query, source_mode, sources, violations)

        references_used = result.get("references_used") or []
        if not isinstance(references_used, list):
            references_used = []
        normalized_refs = [str(item) for item in references_used]

        grounded = dict(result)
        grounded["references_used"] = [item for item in normalized_refs if item in allowed_ids]
        grounded["grounded_source_ids"] = [item["id"] for item in sources]
        grounded["academic_integrity"] = {
            "status": "passed",
            "query": query,
            "source_mode": source_mode,
            "allowed_source_count": len(sources),
            "required_source_count": required_source_count,
            "default_required_source_count": settings.literature_min_grounded_sources,
            "evidence_scope": self.evidence_scope(task, query),
            "violations": [],
        }
        if len(sources) < settings.literature_min_grounded_sources:
            grounded["limited_evidence"] = True
        return grounded

    def required_grounded_source_count(self, task: dict | None, query: str) -> int:
        if not settings.literature_require_grounded_sources:
            return 0
        base = max(int(settings.literature_min_grounded_sources), 0)
        if base <= 1:
            return base
        return base if self.evidence_scope(task, query) == "academic_review" else 1

    def evidence_scope(self, task: dict | None, query: str) -> str:
        text = " ".join(
            [
                str(query or ""),
                str((task or {}).get("title") or ""),
                str((task or {}).get("description") or ""),
            ]
        ).lower()
        if any(marker in text for marker in self.ACADEMIC_MARKERS):
            return "academic_review"
        return "practical_brief"

    @staticmethod
    def _citation_violations(result: dict, sources: list[dict], allowed_ids: set[str]) -> list[str]:
        references_used = result.get("references_used") or []
        if not isinstance(references_used, list):
            references_used = []

        violations: list[str] = []
        unknown_refs = sorted(set(str(item) for item in references_used) - allowed_ids)
        if unknown_refs:
            violations.append(f"unknown source ids: {', '.join(unknown_refs)}")

        serialized = json.dumps(result, ensure_ascii=False)
        bracket_refs = set(re.findall(r"\[(source_[^\]\s]+)\]", serialized))
        unknown_bracket_refs = sorted(bracket_refs - allowed_ids)
        if unknown_bracket_refs:
            violations.append(f"unknown bracket citations: {', '.join(unknown_bracket_refs)}")

        allowed_urls = {str(item.get("url") or "").strip() for item in sources if item.get("url")}
        cited_urls = {item.rstrip('",.;)') for item in re.findall(r"https?://[^\s\]\"')；;，。]+", serialized)}
        unknown_urls = sorted(item for item in cited_urls if item not in allowed_urls)
        if unknown_urls:
            violations.append(f"unknown urls: {', '.join(unknown_urls)}")

        allowed_dois = {str(item.get("doi") or "").strip().lower() for item in sources if item.get("doi")}
        cited_dois = {
            item.lower()
            for item in re.findall(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", serialized, flags=re.IGNORECASE)
        }
        unknown_dois = sorted(item for item in cited_dois if item not in allowed_dois)
        if unknown_dois:
            violations.append(f"unknown dois: {', '.join(unknown_dois)}")
        return violations

    @staticmethod
    def _insufficient_evidence_result(
        query: str,
        source_mode: str,
        sources: list[dict],
        required_source_count: int | None = None,
    ) -> dict:
        required = required_source_count if required_source_count is not None else settings.literature_min_grounded_sources
        return {
            "summary": "证据不足：系统未检索到足够的可核验来源，已停止生成文献结论。",
            "findings": [],
            "deliverables": ["未生成文献综述结论，因为可核验来源数量低于门槛。"],
            "risks": ["继续生成将违反学术诚信策略，可能产生不可核验引用。"],
            "next_steps": [f"扩大检索范围、检查浏览器核验链路，或补充至少 {required} 条可核验来源后重试。"],
            "references_used": [],
            "grounded_source_ids": [item["id"] for item in sources],
            "insufficient_evidence": True,
            "academic_integrity": {
                "status": "insufficient_evidence",
                "query": query,
                "source_mode": source_mode,
                "allowed_source_count": len(sources),
                "required_source_count": required,
                "violations": [],
            },
        }

    @staticmethod
    def _blocked_fabrication_result(query: str, source_mode: str, sources: list[dict], violations: list[str]) -> dict:
        return {
            "summary": "引用校验未通过：输出包含白名单之外的 source_id、URL 或 DOI，已阻断。",
            "findings": [],
            "deliverables": ["未生成文献综述结论，因为引用未全部来自 allowed_sources。"],
            "risks": ["检测到潜在伪造或不可核验引用。"],
            "next_steps": ["只使用 allowed_sources 中的 source_id 引用，或重新检索并核验来源。"],
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
