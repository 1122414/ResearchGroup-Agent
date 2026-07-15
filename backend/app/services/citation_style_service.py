from __future__ import annotations

import re


class CitationStyleService:
    """Render and audit the two citation families used by institutional contracts."""

    @staticmethod
    def mode(style: str) -> str:
        value = str(style or "").lower()
        return "author_date" if any(item in value for item in ("harvard", "apa", "author-date")) else "numeric"

    def in_text(self, sources: list[dict], index: dict[str, int], style: str) -> str:
        if not sources:
            return ""
        if self.mode(style) == "numeric":
            numbers = sorted({index[source["id"]] for source in sources if source["id"] in index})
            return f"[{', '.join(map(str, numbers))}]" if numbers else ""
        labels = list(dict.fromkeys(
            f"{self._author_label(source)}, {source.get('year') or 'n.d.'}" for source in sources
        ))
        return f"({'; '.join(labels)})" if labels else ""

    def bibliography_entry(self, source: dict, number: int, style: str) -> str:
        authors = str(source.get("authors") or "").strip()
        year = source.get("year") or "n.d."
        venue = source.get("venue") or source.get("source_type") or ""
        locator = source.get("doi") or source.get("url") or ""
        title = source.get("title") or ""
        if self.mode(style) == "author_date":
            creator = authors or title
            return f"- {creator} ({year}). {title}. {venue}. {locator}".strip()
        return f"[{number}] {authors} ({year}). {title}. {venue}. {locator}".strip()

    def audit(self, report: str, style: str) -> tuple[int, bool, str]:
        reference_match = re.search(r"(?im)^##+\s*(?:参考文献|references)\s*$", report)
        body = report[: reference_match.start()] if reference_match else report
        references = report[reference_match.end():] if reference_match else ""
        if self.mode(style) == "numeric":
            cited = {int(value) for value in re.findall(r"\[(\d+)\]", body)}
            numbered = {int(value) for value in re.findall(r"(?m)^\s*\[(\d+)\]", references)}
            return len(numbered), bool(cited) and cited <= numbered, (
                f"正文引用={sorted(cited)}，参考文献编号={sorted(numbered)}"
            )

        entries = [line[2:].strip() for line in references.splitlines() if line.startswith("- ")]
        citations: list[tuple[str, str]] = []
        for group in re.findall(r"\(([^()\n]*(?:\d{4}|n\.d\.)[^()\n]*)\)", body, flags=re.I):
            for item in group.split(";"):
                match = re.match(r"\s*(.+?),\s*((?:19|20)\d{2}|n\.d\.)\s*$", item, flags=re.I)
                if match:
                    citations.append((match.group(1).strip(), match.group(2)))
        missing = [
            f"{label}, {year}" for label, year in citations
            if not any(year.lower() in entry.lower() and self._label_token(label) in entry.lower() for entry in entries)
        ]
        return len(entries), bool(citations) and not missing, (
            f"作者-年份引用={len(citations)}，参考文献={len(entries)}，未匹配={missing}"
        )

    def _author_label(self, source: dict) -> str:
        authors = str(source.get("authors") or "").strip()
        if not authors:
            words = re.findall(r"[A-Za-z0-9]+", str(source.get("title") or "Untitled"))
            return " ".join(words[:4]) or "Untitled"
        first = re.split(r"\s*(?:;|\band\b|&)\s*", authors, maxsplit=1, flags=re.I)[0]
        surname = first.split(",", 1)[0].strip() if "," in first else first.split()[-1]
        multiple = bool(re.search(r";|\band\b|&", authors, flags=re.I))
        return f"{surname} et al." if multiple else surname

    @staticmethod
    def _label_token(label: str) -> str:
        return (re.findall(r"[a-z0-9]+", label.lower()) or [""])[0]


citation_style_service = CitationStyleService()
