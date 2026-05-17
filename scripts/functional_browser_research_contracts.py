#!/usr/bin/env python3
"""Functional contract smoke test for browser-assisted literature research.

This script avoids launching a real browser. It monkeypatches the browser
research seam so we can verify the pipeline contract deterministically:

1. Browser-discovered sources can join the evidence bundle.
2. Browser verification metadata is preserved.
3. Rejected sources are removed when strict verification is enabled.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DB_PATH = Path("browser_research_contracts.db")
os.environ["DATABASE_URL"] = f"sqlite:///./{DB_PATH.name}"
os.environ["BROWSER_RESEARCH_ENABLED"] = "true"
os.environ["BROWSER_VERIFICATION_ENABLED"] = "true"
os.environ["BROWSER_VERIFICATION_REQUIRED"] = "true"

from backend.app.core.config import settings  # noqa: E402
from backend.app.services.browser_research_service import browser_research_service  # noqa: E402
from backend.app.services.evidence_pipeline_service import evidence_pipeline_service  # noqa: E402
from backend.app.services.evidence_provider import evidence_provider  # noqa: E402
from backend.app.storage.db import init_db  # noqa: E402
from backend.app.storage.repositories import RunEventRepository, RunRepository  # noqa: E402


async def fake_discover(query: str) -> list[dict]:
    assert "controlled browser verification" in query
    return [
        {
            "id": "https://example.org/accepted-paper",
            "title": "Accepted paper",
            "authors": "Alice Example",
            "year": 2025,
            "venue": "Example Journal",
            "doi": "10.0000/accepted",
            "url": "https://example.org/accepted-paper",
            "source_type": "paper",
            "metadata": {"provider": "browser_use", "content": "browser-discovered"},
        },
        {
            "id": "https://example.org/rejected-paper",
            "title": "Rejected paper",
            "authors": "Bob Example",
            "year": 2024,
            "venue": "Example Journal",
            "doi": "10.0000/rejected",
            "url": "https://example.org/rejected-paper",
            "source_type": "paper",
            "metadata": {"provider": "browser_use", "content": "browser-discovered"},
        },
    ]


async def fake_verify(query: str, sources: list[dict]) -> list[dict]:
    assert "controlled browser verification" in query
    verified: list[dict] = []
    for source in sources:
        metadata = dict(source.get("metadata") or {})
        accepted = source["url"].endswith("accepted-paper")
        metadata["browser_verification"] = {
            "url": source["url"],
            "accepted": accepted,
            "title_match": accepted,
            "doi_match": accepted,
            "evidence": "matched page metadata" if accepted else "",
            "reject_reason": "" if accepted else "page metadata mismatch",
        }
        if accepted or not settings.browser_verification_required:
            verified.append({**source, "metadata": metadata})
    return verified


async def main() -> int:
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()

    RunRepository.insert(
        {
            "id": "run_browser_contract",
            "research_goal": "controlled browser verification",
            "status": "executing",
            "current_step": "evidence",
            "task_ids": [],
            "agent_assignments": {},
            "created_at": "2026-05-17T00:00:00",
            "updated_at": "2026-05-17T00:00:00",
            "started_at": None,
            "completed_at": None,
            "cancel_requested_at": None,
            "cancel_reason": None,
            "total_cost_usd": 0,
            "total_tokens": 0,
            "total_llm_calls": 0,
            "last_event_id": None,
        }
    )

    original_search = evidence_provider.search_with_trace
    original_discover = browser_research_service.discover
    original_verify = browser_research_service.verify_candidates
    evidence_provider.search_with_trace = lambda query: {
        "results": [],
        "attempts": [
            {
                "provider": "openalex",
                "kind": "evidence_provider",
                "enabled": True,
                "result_count": 0,
                "error": None,
            }
        ],
    }
    browser_research_service.discover = fake_discover
    browser_research_service.verify_candidates = fake_verify
    try:
        bundle = await evidence_pipeline_service.collect_for_task(
            {
                "id": "task_browser_contract",
                "run_id": "run_browser_contract",
                "title": "controlled browser verification",
                "description": "controlled browser verification",
            }
        )
        events = RunEventRepository.get_by_run("run_browser_contract", limit=20)
    finally:
        evidence_provider.search_with_trace = original_search
        browser_research_service.discover = original_discover
        browser_research_service.verify_candidates = original_verify
        if DB_PATH.exists():
            DB_PATH.unlink()

    assert bundle["mode"] == "remote_provider+browser_research", bundle["mode"]
    assert len(bundle["sources"]) == 1, bundle["sources"]
    source = bundle["sources"][0]
    assert source["title"] == "Accepted paper"
    verification = source["metadata"]["browser_verification"]
    assert verification["accepted"] is True
    assert verification["doi_match"] is True
    search_event = next(item for item in events if item["event_type"] == "evidence.search.completed")
    verify_event = next(item for item in events if item["event_type"] == "evidence.verification.completed")
    assert search_event["payload"]["attempts"][0]["provider"] == "openalex"
    assert search_event["payload"]["browser_discovered"] == 2
    assert verify_event["payload"]["accepted_count"] == 1
    print("OK - browser research contract smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
