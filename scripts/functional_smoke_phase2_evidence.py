"""Functional smoke test for Phase 2 evidence and argumentation.

Run after starting the backend:
    python scripts/functional_smoke_phase2_evidence.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request


API_BASE = "http://127.0.0.1:8000/api"


def request(method: str, path: str, body: dict | None = None) -> dict:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    print("[1/7] health")
    assert_true(request("GET", "/health").get("status") == "ok", "backend health is not ok")

    print("[2/7] evidence settings and providers")
    settings = request("GET", "/settings")
    for key in [
        "evidence_provider_mode",
        "evidence_remote_search_enabled",
        "evidence_search_max_results",
        "claim_support_threshold",
        "claim_conflict_threshold",
    ]:
        assert_true(key in settings, f"missing setting: {key}")
    providers = request("GET", "/runs/evidence/providers")["items"]
    assert_true(any(item["name"] == "tavily" for item in providers), "missing tavily provider capability")
    assert_true(any(item["name"] == "crossref" for item in providers), "missing crossref provider capability")

    print("[3/7] create run and claim")
    stamp = int(time.time())
    run_id = request("POST", "/runs", {"research_goal": f"phase2 smoke {stamp}"})["run_id"]
    claim = request(
        "POST",
        f"/runs/{run_id}/claims",
        {"statement": "The proposed method improves retrieval quality."},
    )["claim"]

    print("[4/7] register evidence sources and excerpts")
    source_a = request(
        "POST",
        f"/runs/{run_id}/evidence/sources",
        {"title": "Supporting Study", "authors": "A. Author", "year": 2024, "venue": "Journal A"},
    )["source"]
    source_b = request(
        "POST",
        f"/runs/{run_id}/evidence/sources",
        {"title": "Counter Study", "authors": "B. Author", "year": 2023, "venue": "Journal B"},
    )["source"]
    excerpt_a = request(
        "POST",
        f"/runs/{run_id}/evidence/sources/{source_a['id']}/excerpts",
        {"excerpt": "Reported a measurable gain over baseline.", "locator": "p. 3"},
    )["excerpt"]
    excerpt_b = request(
        "POST",
        f"/runs/{run_id}/evidence/sources/{source_b['id']}/excerpts",
        {"excerpt": "Found no significant gain under a stronger baseline.", "locator": "p. 7"},
    )["excerpt"]

    print("[5/7] link support and opposition")
    supported = request(
        "POST",
        f"/runs/{run_id}/evidence/links",
        {
            "claim_id": claim["id"],
            "source_id": source_a["id"],
            "excerpt_id": excerpt_a["id"],
            "relation_type": "supports",
            "confidence": 0.8,
            "rationale": "direct empirical support",
        },
    )["claim"]
    assert_true(supported["status"] == "supported", "claim should become supported")
    contested = request(
        "POST",
        f"/runs/{run_id}/evidence/links",
        {
            "claim_id": claim["id"],
            "source_id": source_b["id"],
            "excerpt_id": excerpt_b["id"],
            "relation_type": "opposes",
            "confidence": 0.5,
            "rationale": "counter evidence",
        },
    )["claim"]
    assert_true(contested["status"] == "contested", "claim should become contested")

    print("[6/7] inspect evidence bundle")
    evidence = request("GET", f"/runs/{run_id}/evidence")
    assert_true(len(evidence["sources"]) == 2, "expected two sources")
    assert_true(len(evidence["excerpts"]) == 2, "expected two excerpts")
    assert_true(len(evidence["links"]) == 2, "expected two links")

    print("[7/7] cleanup")
    deleted = request("DELETE", f"/runs/{run_id}")
    assert_true(deleted.get("deleted") is True, "run cleanup failed")
    print("OK: phase2 evidence smoke passed")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as exc:
        print(f"Backend is not reachable at {API_BASE}: {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
