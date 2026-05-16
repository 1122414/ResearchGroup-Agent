#!/usr/bin/env python3
"""Phase 3-6 functional smoke test for the research workbench upgrade.

Usage:
    1. Start backend with MOCK_MODE=true.
    2. Run: python scripts/functional_research_workbench_upgrade.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request


BASE_URL = "http://localhost:8000/api"
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


def ensure_run_completed(run_id: str, timeout: int = 180) -> dict:
    start = time.time()
    while time.time() - start < timeout:
        summary = req("GET", f"/runs/{run_id}/summary")
        status = summary["run"]["status"]
        if status in FINAL_STATUSES:
            return summary
        if status == "waiting_confirmation":
            approvals = req("GET", f"/runs/{run_id}/approvals")["items"]
            for item in approvals:
                if item["status"] == "pending":
                    req("POST", f"/runs/approvals/{item['id']}/resolve", {"approved": True})
        time.sleep(1)
    raise TimeoutError("run did not finish in time")


def main() -> int:
    print("[1/8] health")
    health = req("GET", "/health")
    assert health["status"] == "ok"

    print("[2/8] create run")
    created = req("POST", "/runs", {"research_goal": "比较不同文档切分策略对检索质量的影响"})
    run_id = created["run_id"]

    print("[3/8] execute run")
    req("POST", f"/runs/{run_id}/start")
    summary = ensure_run_completed(run_id)
    assert summary["run"]["status"] == "completed", summary["run"]

    print("[4/8] research state")
    research_state = req("GET", f"/runs/{run_id}/research-state")
    assert research_state["brief"]
    assert research_state["hypotheses"]
    assert research_state["claims"]

    print("[5/8] experiment closure")
    protocols = req("GET", f"/experiments/protocols?run_id={run_id}")["protocols"]
    results = req("GET", f"/experiments/results?run_id={run_id}")["results"]
    findings = req("GET", f"/experiments/findings?run_id={run_id}")["findings"]
    assert protocols, "missing experiment protocols"
    assert results, "missing experiment results"
    assert findings, "missing experiment findings"

    print("[6/8] research loop")
    loop_snapshot = req("GET", f"/runs/{run_id}/research-loop")
    assert "phase" in loop_snapshot
    assert "gaps" in loop_snapshot
    assert "can_auto_continue" in loop_snapshot

    print("[7/8] artifact manifest")
    manifest = req("GET", f"/runs/{run_id}/artifact-manifest")
    artifact_paths = [item["path"] for item in manifest["artifacts"]]
    assert any(path.endswith("final_report.md") for path in artifact_paths), artifact_paths
    assert any(path.endswith("summary.json") for path in artifact_paths), artifact_paths

    print("[8/8] evidence and claims")
    evidence = req("GET", f"/runs/{run_id}/evidence")
    assert "sources" in evidence and "links" in evidence

    print("\nOK - research workbench upgrade smoke passed")
    print(f"run_id={run_id}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"\nFAILED: {exc}")
        raise SystemExit(1)
    except urllib.error.URLError as exc:
        print(f"\nFAILED: backend unavailable: {exc}")
        raise SystemExit(1)
    except Exception as exc:
        print(f"\nFAILED: {exc}")
        raise SystemExit(1)
