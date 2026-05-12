#!/usr/bin/env python3
"""Lightweight functional smoke test for the 2026-05-12 system hardening work.

Run from the repository root after starting the backend:

    python scripts/functional_smoke_5_12.py

The script deliberately avoids starting a full LLM run. It checks API health,
settings safety, attachment preflight, run creation/deletion, and local helper
contracts that should remain stable during later refactors.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "http://localhost:8000/api"
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))


def req(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def check_local_helpers() -> None:
    print("[1/6] local helper contracts")
    from app.core.research_goal import ATTACHMENT_CONTEXT_HEADING, primary_goal
    from app.core.state_machine import RUN_TRANSITIONS, can_delete_run, check_transition

    mixed_goal = f"研究 A 和 B 的差异\n\n{ATTACHMENT_CONTEXT_HEADING}\n\n### a.pdf\ncontent"
    assert primary_goal(mixed_goal) == "研究 A 和 B 的差异"
    assert check_transition("created", "queued", RUN_TRANSITIONS).ok
    assert not check_transition("completed", "executing", RUN_TRANSITIONS).ok
    assert can_delete_run("created")
    assert can_delete_run("completed")
    assert not can_delete_run("executing")
    print("    OK")


def check_health() -> None:
    print("[2/6] backend health")
    resp = req("GET", "/health")
    assert resp.get("status") == "ok", resp
    print(f"    OK mock_mode={resp.get('mock_mode')} model={resp.get('model')}")


def check_settings_masked() -> None:
    print("[3/6] settings API masks secrets")
    resp = req("GET", "/settings")
    assert "llm_api_key" in resp
    assert resp.get("llm_api_key") == "", "settings API must not return the raw API key"
    assert "has_llm_api_key" in resp
    assert "llm_max_tokens" in resp
    assert "attachment_extract_max_chars" in resp
    masked = str(resp.get("llm_api_key_masked") or "")
    assert not masked.startswith("sk-"), "masked key should not expose provider key prefix"
    print("    OK")


def check_attachment_preflight() -> None:
    print("[4/6] attachment preflight")
    resp = req(
        "POST",
        "/runs/preflight",
        {
            "research_goal": "附件预检冒烟",
            "attachments": [
                {
                    "name": "notes.md",
                    "mime_type": "text/markdown",
                    "size": 18,
                    "data_url": "data:text/markdown;base64,IyBUZXN0Cg==",
                }
            ],
        },
    )
    assert resp.get("ok") is True, resp
    assert "limits" in resp, resp
    print("    OK")


def check_create_query_delete_run() -> None:
    print("[5/6] create, query, delete run")
    created = req("POST", "/runs", {"research_goal": "功能测试：配置集中与状态边界", "attachments": []})
    run_id = created.get("run_id")
    assert run_id, created
    detail = req("GET", f"/runs/{run_id}")
    assert detail.get("run", {}).get("id") == run_id
    assert detail.get("run", {}).get("status") == "created"
    deleted = req("DELETE", f"/runs/{run_id}")
    assert deleted.get("deleted") is True
    print(f"    OK run_id={run_id}")


def check_runs_list() -> None:
    print("[6/6] runs list")
    resp = req("GET", "/runs")
    assert isinstance(resp.get("runs"), list)
    print(f"    OK runs={len(resp.get('runs', []))}")


def main() -> int:
    try:
        check_local_helpers()
        check_health()
        check_settings_masked()
        check_attachment_preflight()
        check_create_query_delete_run()
        check_runs_list()
    except AssertionError as exc:
        print(f"\nFAILED: {exc}")
        return 1
    except urllib.error.URLError as exc:
        print(f"\nFAILED: cannot reach backend at {BASE_URL}: {exc}")
        print("Start it with: cd backend && python main.py")
        return 1
    except Exception as exc:
        print(f"\nFAILED: {exc}")
        return 1

    print("\nAll smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
