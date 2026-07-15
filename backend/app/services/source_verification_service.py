from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from ..core.config import settings
from ..core.logger import logger


class SourceVerificationService:
    """Verify a source's DOI by resolving it and cross-checking title/year.

    Helps catch hallucinated or mismatched citations: a source whose DOI does not
    resolve, or whose resolved title/year do not match the claimed metadata, is
    marked unverified so downstream grounding/reporting can flag it.
    """

    def verify_sources(self, sources: list[dict]) -> list[dict]:
        for source in sources:
            metadata = dict(source.get("metadata") or {})
            verdict = self._verify_one(source) if settings.doi_verification_enabled else None
            if verdict is not None:
                metadata["doi_verification"] = verdict
                if verdict.get("verified"):
                    self._enrich_verified_bibliography(source, verdict)
                    metadata["bibliographic_enrichment_source"] = "crossref_doi_resolution"
            status, eligible = self._citation_status(source, metadata, verdict)
            metadata["verification_status"] = status
            metadata["citation_eligible"] = eligible
            source["metadata"] = metadata
        return sources

    @staticmethod
    def _citation_status(source: dict, metadata: dict, doi_verdict: dict | None) -> tuple[str, bool]:
        """Classify citation identity without pretending metadata proves content."""
        if doi_verdict and doi_verdict.get("status") in {"mismatch", "unresolved"}:
            return f"doi_{doi_verdict['status']}", False
        if doi_verdict and doi_verdict.get("verified"):
            return "doi_verified", True

        browser = metadata.get("browser_verification") or {}
        if browser.get("accepted") and browser.get("fallback") != "search_result_metadata":
            return "browser_verified", True

        provider = metadata.get("provider")
        traceable = bool(source.get("doi") or source.get("url") or metadata.get("canonical_id"))
        if provider in {"crossref", "openalex", "arxiv", "semantic_scholar"} and traceable:
            return "scholarly_metadata_verified", True
        return "unverified", False

    @staticmethod
    def citation_eligible(source: dict) -> bool:
        return bool((source.get("metadata") or {}).get("citation_eligible"))

    def _verify_one(self, source: dict) -> dict:
        doi = self._normalize_doi(source.get("doi"))
        if not doi:
            return {"status": "no_doi", "verified": False}
        fetched = self._fetch_crossref(doi)
        if fetched is None:
            return {"status": "unresolved", "verified": False, "doi": doi}
        return self._verdict(source, fetched)

    def _verdict(self, source: dict, fetched: dict) -> dict:
        title_ok = self._title_matches(source.get("title", ""), fetched.get("title", ""))
        year_ok = self._year_matches(source.get("year"), fetched.get("year"))
        verified = bool(title_ok and (year_ok or source.get("year") is None))
        status = "verified" if verified else "mismatch"
        return {
            "status": status,
            "verified": verified,
            "title_match": title_ok,
            "year_match": year_ok,
            "resolved_title": fetched.get("title", ""),
            "resolved_year": fetched.get("year"),
            "resolved_authors": fetched.get("authors", ""),
            "resolved_venue": fetched.get("venue", ""),
        }

    @staticmethod
    def _enrich_verified_bibliography(source: dict, verdict: dict) -> None:
        for field, resolved in (
            ("authors", verdict.get("resolved_authors")),
            ("year", verdict.get("resolved_year")),
            ("venue", verdict.get("resolved_venue")),
        ):
            if source.get(field) in (None, "") and resolved not in (None, ""):
                source[field] = resolved

    @staticmethod
    def _title_matches(claimed: str, resolved: str) -> bool:
        def tokens(text: str) -> set[str]:
            return {t for t in re.findall(r"[a-z0-9\u4e00-\u9fff]+", str(text).lower()) if len(t) > 2}

        a, b = tokens(claimed), tokens(resolved)
        if not a or not b:
            return False
        overlap = len(a & b) / min(len(a), len(b))
        return overlap >= 0.6

    @staticmethod
    def _year_matches(claimed, resolved) -> bool:
        try:
            return abs(int(claimed) - int(resolved)) <= 1
        except (TypeError, ValueError):
            return False

    def _fetch_crossref(self, doi: str) -> dict | None:
        url = f"{settings.crossref_base_url.rstrip('/')}/works/{urllib.parse.quote(doi)}"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "ResearchGroup-Agent/1.0"})
            with urllib.request.urlopen(request, timeout=settings.evidence_search_timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError) as exc:
            logger.debug("[SourceVerification] crossref fetch failed | doi=%s | error=%s", doi, exc)
            return None
        message = body.get("message", {})
        published = (
            message.get("published-print", {}).get("date-parts")
            or message.get("issued", {}).get("date-parts")
            or []
        )
        year = published[0][0] if published and published[0] else None
        authors = "; ".join(
            " ".join(filter(None, (author.get("given"), author.get("family"))))
            for author in message.get("author") or []
            if author.get("given") or author.get("family")
        )
        return {
            "title": (message.get("title") or [""])[0], "year": year,
            "authors": authors, "venue": (message.get("container-title") or [""])[0],
        }

    @staticmethod
    def _normalize_doi(value) -> str | None:
        if not value:
            return None
        normalized = str(value).strip()
        for prefix in ("https://doi.org/", "http://doi.org/"):
            if normalized.lower().startswith(prefix):
                normalized = normalized[len(prefix):]
        return normalized or None


source_verification_service = SourceVerificationService()
