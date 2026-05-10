"""
P0 functional smoke test for ResearchGroup-Agent.

Prerequisites:
1. Backend dependencies installed: cd backend && pip install -r requirements.txt
2. Backend running: cd backend && python main.py
3. Prefer MOCK_MODE=true for deterministic local smoke tests.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request


BACKEND_URL = "http://localhost:8000"
TIMEOUT = 180


def request(method: str, path: str, data: dict | None = None) -> dict:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(f"{BACKEND_URL}{path}", data=body, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {path} failed: {exc}") from exc


def ok(message: str):
    print(f"[OK] {message}")


def check(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)
    ok(message)


def main() -> int:
    print("== ResearchGroup-Agent P0 functional smoke ==")
    health = request("GET", "/api/health")
    check(health.get("status") == "ok", "backend health is ok")
    print(f"[INFO] mock_mode={health.get('mock_mode')} model={health.get('model')}")

    goal = "验证 P0 可观测运行链路：任务拆解、事件日志、成本记录、运行详情和停止接口。"
    created = request("POST", "/api/runs", {"research_goal": goal})
    run_id = created["run_id"]
    ok(f"created run {run_id}")

    summary = request("GET", f"/api/runs/{run_id}/summary")
    check(summary["run"]["status"] == "created", "new run is created")

    result = request("POST", f"/api/runs/{run_id}/start")
    check(result["run"]["status"] in {"completed", "failed", "cancelled"}, "start endpoint returns a terminal summary")

    summary = request("GET", f"/api/runs/{run_id}/summary")
    check(summary["counts"]["tasks_total"] >= 3, "tasks were decomposed")
    check(summary["usage"]["total_llm_calls"] >= 1, "llm usage was recorded")

    events = request("GET", f"/api/runs/{run_id}/events?limit=200")["events"]
    event_types = {event["event_type"] for event in events}
    check("run.created" in event_types, "run.created event exists")
    check("phase.started" in event_types, "phase.started event exists")
    check("task.assigned" in event_types, "task.assigned event exists")

    usage = request("GET", f"/api/runs/{run_id}/usage")
    check(len(usage["items"]) == summary["usage"]["total_llm_calls"], "usage detail count matches summary")

    outputs = request("GET", f"/api/outputs?run_id={run_id}")["outputs"]
    check(any(output["output_type"] == "final_report" for output in outputs), "final report output exists")

    cancel_created = request("POST", "/api/runs", {"research_goal": "验证未开始运行的停止接口。"})
    cancel_run_id = cancel_created["run_id"]
    cancel_result = request("POST", f"/api/runs/{cancel_run_id}/cancel", {"reason": "P0 smoke test"})
    check(cancel_result["run"]["status"] == "cancelled", "created run can be cancelled before start")

    print("== P0 smoke passed ==")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
