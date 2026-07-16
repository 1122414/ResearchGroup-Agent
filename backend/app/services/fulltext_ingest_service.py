from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from io import BytesIO

from ..core.config import settings
from ..core.logger import logger
from ..storage.repositories import EvidenceRepository, FullTextDocumentRepository


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
        existing = {
            (item["source_id"], item["url"])
            for item in FullTextDocumentRepository.get_by_run(run_id)
        }
        # A resource cap below the configured literature deliverable makes every
        # revision impossible. Keep the two limits consistent at execution time.
        source_limit = max(settings.fulltext_max_sources, settings.literature_source_limit)
        for source in sources[:source_limit]:
            url = source.get("url")
            if not url:
                continue
            if (source["id"], url) in existing:
                ingested += 1
                continue
            text, parser = self._fetch_text(url)
            if not text:
                continue
            text = text[: settings.fulltext_max_chars]
            content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            document_id = f"document_{uuid.uuid4().hex[:10]}"
            now = datetime.now().isoformat()
            FullTextDocumentRepository.insert(
                {
                    "id": document_id, "run_id": run_id, "source_id": source["id"], "url": url,
                    "content_hash": content_hash, "parser": parser, "status": "parsed",
                    "char_count": len(text), "created_at": now,
                }
            )
            existing.add((source["id"], url))
            for index, start in enumerate(range(0, len(text), settings.evidence_excerpt_max_chars)):
                passage = text[start : start + settings.evidence_excerpt_max_chars].strip()
                if not passage:
                    continue
                EvidenceRepository.insert_excerpt(
                    {
                        "id": f"excerpt_{uuid.uuid4().hex[:10]}", "run_id": run_id,
                        "source_id": source["id"], "excerpt": passage,
                        "locator": f"{url}#chars={start}-{start + len(passage)}", "excerpt_type": "fulltext",
                        "captured_at": now, "document_id": document_id, "section": "",
                        "page_number": None, "paragraph_index": index, "content_hash": content_hash,
                    }
                )
            ingested += 1
        if ingested:
            logger.info("[FulltextIngest] ingested full text | run_id=%s | sources=%d", run_id, ingested)
        return ingested

    def _fetch_text(self, url: str) -> tuple[str, str]:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "ResearchGroup-Agent/1.0"})
            with urllib.request.urlopen(request, timeout=settings.fulltext_fetch_timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                raw = response.read(4 * 1024 * 1024)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            logger.debug("[FulltextIngest] fetch failed | url=%s | error=%s", url, exc)
            return "", "fetch_failed"

        if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
            return self._usable_text(self._extract_pdf(raw)), "pdf"
        if raw.startswith(b"PK\x03\x04") or raw.count(b"\x00") > max(len(raw) // 100, 8):
            return "", "unsupported_binary"
        try:
            html = raw.decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            return "", "html"
        return self._usable_text(self._strip_html(html)), "html"

    @staticmethod
    def _usable_text(text: str) -> str:
        text = str(text or "").strip()
        if len(text) < 200:
            return ""
        readable = sum(character.isprintable() for character in text) / len(text)
        letters = sum(character.isalpha() for character in text)
        return text if readable >= 0.9 and letters >= 100 else ""

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
