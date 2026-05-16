from __future__ import annotations


class EvidenceProvider:
    def list_capabilities(self) -> list[dict]:
        return [
            {"name": "local_attachment", "enabled": True},
            {"name": "manual_metadata", "enabled": True},
            {"name": "crossref", "enabled": False},
            {"name": "arxiv", "enabled": False},
            {"name": "semantic_scholar", "enabled": False},
            {"name": "zotero", "enabled": False},
        ]

    def search(self, query: str) -> list[dict]:
        return []

    def register_source(self, source: dict) -> dict:
        return source

    def resolve_source(self, source_id: str) -> dict | None:
        return None


evidence_provider = EvidenceProvider()
