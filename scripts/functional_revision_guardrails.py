#!/usr/bin/env python3
"""Regression checks for literature revision guardrails."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DB_PATH = Path("revision_guardrails.db")
os.environ["DATABASE_URL"] = f"sqlite:///./{DB_PATH.name}"
os.environ["TASK_MAX_REVISION_ROUNDS"] = "2"

from backend.app.services.evidence_pipeline_service import evidence_pipeline_service  # noqa: E402
from backend.app.services.task_recovery_service import task_recovery_service  # noqa: E402
from backend.app.storage.db import init_db  # noqa: E402
from backend.app.storage.repositories import TaskRepository  # noqa: E402


def seed_task() -> dict:
    now = datetime.now().isoformat()
    task = {
        "id": "task_root",
        "title": "文献综述：Telegram 电诈常见手法",
        "description": "系统检索 Telegram 电诈常见手法并总结演进趋势",
        "task_type": "literature_survey",
        "required_skills": {},
        "priority": 5,
        "complexity": 5,
        "decomposability": 5,
        "status": "need_revision",
        "owner_agent": "grad_researcher",
        "collaborator_agents": [],
        "subtasks": [],
        "outputs": [],
        "review_result": None,
        "review_feedback": "补充可信来源",
        "run_id": "run_revision_guardrails",
        "assignment_info": {},
        "subagent_triggered": False,
        "blocked_reason": None,
        "parallelizable": True,
        "is_critical_path": True,
        "attempt_count": 0,
        "last_checkpoint": None,
        "revision_of_task_id": None,
        "created_at": now,
        "updated_at": now,
    }
    TaskRepository.insert(task)
    return task


def main() -> int:
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    root = seed_task()
    first = task_recovery_service.create_revision_task(root, "第一次返工")
    assert first is not None
    assert first["title"] == "返工：文献综述：Telegram 电诈常见手法"
    assert first["revision_of_task_id"] == root["id"]
    assert "原始任务：" in first["description"]
    assert evidence_pipeline_service._query_for_task(first) == (
        "系统检索 Telegram 电诈常见手法并总结演进趋势 文献综述：Telegram 电诈常见手法"
    )

    TaskRepository.update_status(first["id"], "completed")
    second = task_recovery_service.create_revision_task(first, "第二次返工")
    assert second is not None
    assert second["title"] == "返工：文献综述：Telegram 电诈常见手法"
    assert second["revision_of_task_id"] == root["id"]

    TaskRepository.update_status(second["id"], "completed")
    third = task_recovery_service.create_revision_task(second, "第三次返工")
    assert third is None

    if DB_PATH.exists():
        DB_PATH.unlink()
    print("OK - revision guardrails smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
