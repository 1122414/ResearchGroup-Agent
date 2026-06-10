from __future__ import annotations

import re

from ..core.config import settings

# Sections whose bullet items are presented as factual conclusions and therefore
# should carry an inline [n] citation when claimed from sources.
_CLAIM_SECTIONS = ("结果", "结论", "关键结论", "主题与发现", "Results", "Findings")
_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


class GroundingAuditService:
    """Scan an assembled report body for ungrounded or invalid citations.

    The paper assembler builds citations deterministically, but the embedded LLM
    narrative and any manual edits can introduce bracket citations that point past
    the reference list, or factual bullet claims with no citation at all. This
    audit reports both so the run surfaces grounding quality instead of trusting
    the prose blindly.
    """

    def audit_report(self, report_md: str) -> dict:
        if not settings.grounding_audit_enabled:
            return {"checked": False, "reason": "grounding_audit_disabled"}
        reference_count = self._reference_count(report_md)
        invalid_citations = self._invalid_citations(report_md, reference_count)
        uncited = self._uncited_claims(report_md)
        return {
            "checked": True,
            "reference_count": reference_count,
            "invalid_citations": invalid_citations,
            "uncited_claim_count": len(uncited),
            "uncited_examples": uncited[:8],
            "passed": not invalid_citations and not uncited,
        }

    def _reference_count(self, report_md: str) -> int:
        in_refs = False
        count = 0
        for line in report_md.splitlines():
            stripped = line.strip()
            if stripped.startswith("## ") and ("参考文献" in stripped or "References" in stripped):
                in_refs = True
                continue
            if in_refs and stripped.startswith("## "):
                break
            if in_refs and re.match(r"^\[\d+\]", stripped):
                count += 1
        return count

    def _invalid_citations(self, report_md: str, reference_count: int) -> list[int]:
        body = self._strip_references(report_md)
        invalid: set[int] = set()
        for match in _CITATION.finditer(body):
            for token in match.group(1).split(","):
                number = int(token.strip())
                if number < 1 or number > reference_count:
                    invalid.add(number)
        return sorted(invalid)

    def _uncited_claims(self, report_md: str) -> list[str]:
        uncited: list[str] = []
        current_section = ""
        for line in report_md.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                current_section = stripped.lstrip("# ").strip()
                continue
            if not any(marker in current_section for marker in _CLAIM_SECTIONS):
                continue
            if not stripped.startswith("- "):
                continue
            text = stripped[2:].strip()
            if len(text) < 12:
                continue
            if not _CITATION.search(text):
                uncited.append(text[:160])
        return uncited

    @staticmethod
    def _strip_references(report_md: str) -> str:
        lines: list[str] = []
        in_refs = False
        for line in report_md.splitlines():
            stripped = line.strip()
            if stripped.startswith("## ") and ("参考文献" in stripped or "References" in stripped):
                in_refs = True
                continue
            if in_refs and stripped.startswith("## "):
                in_refs = False
            if not in_refs:
                lines.append(line)
        return "\n".join(lines)


grounding_audit_service = GroundingAuditService()
