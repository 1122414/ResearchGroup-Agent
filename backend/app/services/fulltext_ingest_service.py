from __future__ import annotations

import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from io import BytesIO

from ..core.config import settings
from ..core.logger import logger
from ..storage.repositories import EvidenceRepository


class FulltextIngestService:
    """Fetch and store real full text for top sources.

    Without this the agent reasons only over titles/abstracts/metadata. Here we
    download the source URL (PDF or HTML), extract readable text, and persist it
    as a full-text excerpt with a locator so later citations point at real
    passages. Network/parse failures degrade gracefully to metadata-only.
    """

    def ingest_sources(self, run_id: str, sources: list[dict]) -> int:
        if not settings.fulltext_ingest_enabled or not run_id:
            return 0
        ingested = 0
        for source in sources[: settings.fulltext_max_sources]:
            url = source.get("url")
            if not url:
                continue
            text = self._fetch_text(url)
            if not text:
                continue
            EvidenceRepository.insert_excerpt(
                {
                    "id": f"excerpt_{uuid.uuid4().hex[:10]}",
                    "run_id": run_id,
                    "source_id": source["id"],
                    "excerpt": text[: settings.fulltext_max_chars],
                    "locator": url,
                    "excerpt_type": "fulltext",
                    "captured_at": datetime.now().isoformat(),
                }
            )
            ingested += 1
        if ingested:
            logger.info("[FulltextIngest] ingested full text | run_id=%s | sources=%d", run_id, ingested)
        return ingested

    def _fetch_text(self, url: str) -> str:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "ResearchGroup-Agent/1.0"})
            with urllib.request.urlopen(request, timeout=settings.fulltext_fetch_timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                raw = response.read(4 * 1024 * 1024)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            logger.debug("[FulltextIngest] fetch failed | url=%s | error=%s", url, exc)
            return ""

        if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
            return self._extract_pdf(raw)
        try:
            html = raw.decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            return ""
        return self._strip_html(html)

    @staticmethod
    def _extract_pdf(raw: bytes) -> str:
        try:
            try:
                from pypdf import PdfReader
            except Exception:  # noqa: BLE001
                from PyPDF2 import PdfReader
            reader = PdfReader(BytesIO(raw))
            pages = [page.extract_text() or "" for page in reader.pages]
            return re.sub(r"\s+", " ", "\n".join(pages)).strip()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[FulltextIngest] pdf parse failed | error=%s", exc)
            return ""

    @staticmethod
    def _strip_html(html: str) -> str:
        html = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        text = re.sub(r"&[a-z]+;", " ", text)
        return re.sub(r"\s+", " ", text).strip()


fulltext_ingest_service = FulltextIngestService()
