#!/usr/bin/env python3
"""Regression checks for grouped insufficient-evidence approvals."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DB_PATH = Path("grouped_revision_approvals.db")
os.environ["DATABASE_URL"] = f"sqlite:///./{DB_PATH.name}"

from backend.app.api.routes_runs import ApprovalResolutionRequest, resolve_approval  # noqa: E402
from backend.app.services.approval_service import approval_service  # noqa: E402
from backend.app.storage.db import init_db  # noqa: E402
from backend.app.storage.repositories import ApprovalRequestRepository, RunRepository, TaskRepository  # noqa: E402


def task(task_id: str, title: str) -> dict:
    now = datetime.now().isoformat()
    return {
        "id": task_id,
        "title": title,
        "description": title,
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
        "review_feedback": None,
        "run_id": "run_grouped_approval",
        "assignment_info": {},
        "subagent_triggered": False,
        "blocked_reason": None,
        "parallelizable": True,
        "is_critical_path": False,
        "attempt_count": 0,
        "last_checkpoint": None,
        "revision_of_task_id": None,
        "created_at": now,
        "updated_at": now,
    }


def seed() -> None:
    now = datetime.now().isoformat()
    RunRepository.insert(
        {
            "id": "run_grouped_approval",
            "research_goal": "group identical insufficient-evidence approvals",
            "status": "reviewing",
            "current_step": "reviewing",
            "task_ids": [],
            "agent_assignments": {},
            "created_at": now,
            "updated_at": now,
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
    TaskRepository.insert(task("task_revision_a", "返工：诈骗手法调研"))
    TaskRepository.insert(task("task_revision_b", "返工：应对方法调研"))


async def main() -> int:
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    seed()

    first = approval_service.ensure_grouped_pending(
        "run_grouped_approval",
        "revision_required",
        "revision_required:insufficient_evidence_guardrail",
        "导师要求返工",
        "同类证据不足",
        task_id="task_a",
        revision_task_id="task_revision_a",
        task_title="诈骗手法调研",
    )
    second = approval_service.ensure_grouped_pending(
        "run_grouped_approval",
        "revision_required",
        "revision_required:insufficient_evidence_guardrail",
        "导师要求返工",
        "同类证据不足",
        task_id="task_b",
        revision_task_id="task_revision_b",
        task_title="应对方法调研",
    )

    assert first["id"] == second["id"]
    pending = ApprovalRequestRepository.get_by_run("run_grouped_approval", status="pending")
    assert len(pending) == 1
    grouped = pending[0]
    assert grouped["title"] == "导师要求返工（2 项）"
    assert grouped["payload"]["task_ids"] == ["task_a", "task_b"]
    assert grouped["payload"]["revision_task_ids"] == ["task_revision_a", "task_revision_b"]

    await resolve_approval(
        grouped["id"],
        ApprovalResolutionRequest(approved=True, resolved_by="functional_test"),
        BackgroundTasks(),
    )
    assert TaskRepository.get_by_id("task_revision_a")["status"] == "pending"
    assert TaskRepository.get_by_id("task_revision_b")["status"] == "pending"

    if DB_PATH.exists():
        DB_PATH.unlink()
    print("OK - grouped revision approvals smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
