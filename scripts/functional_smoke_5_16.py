"""Smoke test for the 2026-05-16 research workbench foundation.

Run this after starting the backend:
    python scripts/functional_smoke_5_16.py
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
    print("[1/5] health")
    health = request("GET", "/health")
    assert_true(health.get("status") == "ok", "backend health is not ok")

    print("[2/5] configurable runtime settings")
    settings = request("GET", "/settings")
    required_settings = [
        "literature_source_limit",
        "literature_fallback_source_count",
        "reproducible_experiment_timeout_seconds",
        "review_pass_threshold",
        "run_artifact_title_max_length",
    ]
    for key in required_settings:
        assert_true(key in settings, f"missing setting: {key}")

    print("[3/5] create run with research state")
    stamp = int(time.time())
    created = request(
        "POST",
        "/runs",
        {"research_goal": f"smoke research goal {stamp}: validate research state foundation"},
    )
    run_id = created["run_id"]
    assert_true(bool(run_id), "run creation did not return run_id")

    state = request("GET", f"/runs/{run_id}/research-state")
    assert_true(bool(state.get("brief")), "research brief was not created")
    assert_true(state["brief"]["run_id"] == run_id, "brief is attached to the wrong run")
    assert_true(state.get("hypotheses") == [], "new runs should not fabricate hypotheses")
    assert_true(state.get("claims") == [], "new runs should not fabricate claims")
    assert_true(len(state.get("decisions", [])) == 1, "expected one initial research decision")
    open_uncertainties = [item for item in state.get("uncertainties", []) if item.get("status") == "open"]
    assert_true(len(open_uncertainties) == 1, "expected one initial open uncertainty")

    print("[4/5] dashboard research summary")
    overview = request("GET", f"/dashboard/overview?run_id={run_id}")
    summary = overview.get("research_state") or {}
    assert_true(summary.get("has_brief") is True, "dashboard summary should expose the brief")
    assert_true(summary.get("hypothesis_count") == 0, "new run should start with zero hypotheses")
    assert_true(summary.get("claim_count") == 0, "new run should start with zero claims")
    assert_true(summary.get("open_uncertainty_count") == 1, "dashboard should expose the open uncertainty")

    print("[5/5] cleanup")
    deleted = request("DELETE", f"/runs/{run_id}")
    assert_true(deleted.get("deleted") is True, "run cleanup failed")

    print("OK: 5.16 functional smoke passed")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as exc:
        print(f"Backend is not reachable at {API_BASE}: {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
