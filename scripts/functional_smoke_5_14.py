"""Smoke test for the 2026-05-14 configuration, Skill, and experiment work.

Run this after starting the backend:
    python scripts/functional_smoke_5_14.py

The script does not enable experiment execution by itself. If execution is
disabled in .env, it verifies review APIs and skips the execute endpoint.
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


def assert_true(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def main():
    print("[1/6] health")
    health = request("GET", "/health")
    assert_true(health["status"] == "ok", "backend health is not ok")

    print("[2/6] settings")
    settings = request("GET", "/settings")
    required_keys = [
        "agent_skill_enabled",
        "skill_auto_capture_enabled",
        "experiment_execution_enabled",
        "experiment_workspace_dir",
        "experiment_require_review",
    ]
    for key in required_keys:
        assert_true(key in settings, f"missing setting: {key}")
    assert_true(settings.get("llm_api_key") == "", "settings must not expose llm_api_key")

    print("[3/6] agent skill CRUD")
    stamp = int(time.time())
    created = request(
        "POST",
        "/agent-skills",
        {
            "agent_id": "advisor",
            "title": f"smoke skill {stamp}",
            "description": "created by functional smoke test",
            "content": "# Smoke Skill\n\nUse this only for API smoke testing.",
            "status": "active",
            "confidence": 0.99,
            "tags": ["smoke", "5.14"],
        },
    )["skill"]
    skill_id = created["id"]
    updated = request("PATCH", f"/agent-skills/{skill_id}", {"description": "updated by smoke test"})["skill"]
    assert_true(updated["description"] == "updated by smoke test", "skill update failed")
    disabled = request("POST", f"/agent-skills/{skill_id}/disable")["skill"]
    assert_true(disabled["status"] == "disabled", "skill disable failed")
    enabled = request("POST", f"/agent-skills/{skill_id}/enable")["skill"]
    assert_true(enabled["status"] == "active", "skill enable failed")

    print("[4/6] experiment plan review flow")
    plan = request(
        "POST",
        "/experiments/plans",
        {
            "agent_id": "experiment_agent",
            "title": f"smoke experiment {stamp}",
            "objective": "verify experiment review APIs",
            "commands": [{"command": "python -c \"print('experiment ok')\""}],
            "files": [{"path": "smoke_input.txt", "content": "hello"}],
            "env_vars": {"RGA_SMOKE": "1"},
        },
    )["plan"]
    plan_id = plan["id"]
    scanned = request("POST", f"/experiments/plans/{plan_id}/scan")["plan"]
    assert_true(scanned["risk_level"] in {"safe", "needs_review", "dangerous"}, "invalid risk level")
    approved = request("POST", f"/experiments/plans/{plan_id}/approve", {"approved_by": "smoke"})["plan"]
    assert_true(approved["status"] == "approved", "experiment approve failed")

    print("[5/6] optional experiment execution")
    config = request("GET", "/experiments/config")["config"]
    if config.get("experiment_execution_enabled"):
        executed = request("POST", f"/experiments/plans/{plan_id}/execute")["plan"]
        assert_true(executed["status"] in {"completed", "failed"}, "experiment execution did not finish")
    else:
        print("      skipped: experiment_execution_enabled=false")

    print("[6/6] cleanup")
    archived = request("DELETE", f"/agent-skills/{skill_id}")["skill"]
    assert_true(archived["status"] == "archived", "skill archive failed")

    print("OK: 5.14 functional smoke passed")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as exc:
        print(f"Backend is not reachable at {API_BASE}: {exc}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)

