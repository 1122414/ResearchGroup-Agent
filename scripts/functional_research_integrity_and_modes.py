#!/usr/bin/env python3
"""Functional smoke test for grounded literature, run modes, and run deletion.

Usage:
    1. Start backend with MOCK_MODE=true.
    2. Run: python scripts/functional_research_integrity_and_modes.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request


BASE_URL = os.environ.get("FUNCTIONAL_TEST_BASE_URL", "http://localhost:8000/api")
FINAL_STATUSES = {"completed", "failed", "cancelled"}


def req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_status(run_id: str, expected: set[str], timeout: int = 180) -> dict:
    started = time.time()
    while time.time() - started < timeout:
        summary = req("GET", f"/runs/{run_id}/summary")
        status = summary["run"]["status"]
        if status in expected:
            return summary
        time.sleep(1)
    raise TimeoutError(f"run {run_id} did not reach {expected}")


def latest_literature_output(summary: dict) -> dict:
    for task in summary["tasks"]:
        if task.get("task_type") == "literature_survey" and task.get("outputs"):
            latest = task["outputs"][-1]
            if isinstance(latest, dict):
                return latest
    raise AssertionError("missing literature output")


def patch_settings(**values) -> dict:
    return req("PATCH", "/settings", values)["updated"]


def main() -> int:
    print("[1/7] health")
    health = req("GET", "/health")
    assert health["status"] == "ok"

    print("[2/7] inspect new settings")
    settings = req("GET", "/settings")
    for key in [
        "web_search_enabled",
        "web_search_provider_mode",
        "literature_require_grounded_sources",
        "citation_validation_enabled",
        "run_interaction_mode",
    ]:
        assert key in settings, key

    original = {
        "run_interaction_mode": settings["run_interaction_mode"],
        "web_search_enabled": settings["web_search_enabled"],
        "evidence_remote_search_enabled": settings["evidence_remote_search_enabled"],
        "literature_require_grounded_sources": settings["literature_require_grounded_sources"],
        "citation_validation_enabled": settings["citation_validation_enabled"],
    }

    try:
        print("[3/7] auto mode grounded run")
        patch_settings(
            run_interaction_mode="auto",
            web_search_enabled=False,
            evidence_remote_search_enabled=False,
            literature_require_grounded_sources=True,
            citation_validation_enabled=True,
        )
        created = req("POST", "/runs", {"research_goal": f"totally novel topic without curated matches {int(time.time())}"})
        auto_run_id = created["run_id"]
        auto_summary = req("POST", f"/runs/{auto_run_id}/run_all")
        assert auto_summary["run"]["status"] == "completed", auto_summary["run"]
        literature_output = latest_literature_output(auto_summary)
        assert literature_output.get("insufficient_evidence") is True
        assert literature_output.get("references_used") == []
        assert literature_output.get("academic_integrity", {}).get("status") == "insufficient_evidence"

        print("[4/7] provider capabilities")
        providers = req("GET", "/runs/evidence/providers")["items"]
        assert any(item["name"] == "tavily" and item.get("kind") == "web_search" for item in providers)

        print("[5/7] hitl run reaches confirmation")
        patch_settings(run_interaction_mode="hitl")
        created = req("POST", "/runs", {"research_goal": f"hitl deletion smoke {int(time.time())}"})
        hitl_run_id = created["run_id"]
        hitl_summary = req("POST", f"/runs/{hitl_run_id}/run_all")
        assert hitl_summary["run"]["status"] == "waiting_confirmation"

        print("[6/7] delete paused run")
        deleted = req("DELETE", f"/runs/{hitl_run_id}")
        assert deleted["deleted"] is True

        print("[7/7] cleanup")
        req("DELETE", f"/runs/{auto_run_id}")
    finally:
        patch_settings(**original)

    print("\nOK - research integrity and modes smoke passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except urllib.error.URLError as exc:
        print(f"\nFAILED: backend unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
