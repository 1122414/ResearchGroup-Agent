"""State transition guards for run and task lifecycle boundaries."""

from dataclasses import dataclass

from fastapi import HTTPException

from ..models.run import RunStatus
from ..models.task import TaskStatus


FINAL_RUN_STATUSES = {RunStatus.completed.value, RunStatus.failed.value, RunStatus.cancelled.value}

RUN_TRANSITIONS: dict[str, set[str]] = {
    RunStatus.created.value: {RunStatus.queued.value, RunStatus.decomposing.value, RunStatus.cancelled.value},
    RunStatus.queued.value: {RunStatus.decomposing.value, RunStatus.cancelled.value, RunStatus.failed.value},
    RunStatus.decomposing.value: {RunStatus.scheduling.value, RunStatus.cancelling.value, RunStatus.failed.value},
    RunStatus.scheduling.value: {RunStatus.executing.value, RunStatus.cancelling.value, RunStatus.failed.value},
    RunStatus.executing.value: {RunStatus.reviewing.value, RunStatus.waiting_confirmation.value, RunStatus.reporting.value, RunStatus.cancelling.value, RunStatus.failed.value},
    RunStatus.reviewing.value: {RunStatus.executing.value, RunStatus.waiting_confirmation.value, RunStatus.reporting.value, RunStatus.cancelling.value, RunStatus.failed.value},
    RunStatus.waiting_confirmation.value: {RunStatus.executing.value, RunStatus.reporting.value, RunStatus.cancelling.value, RunStatus.failed.value},
    RunStatus.reporting.value: {RunStatus.completed.value, RunStatus.cancelling.value, RunStatus.failed.value},
    RunStatus.cancelling.value: {RunStatus.cancelled.value, RunStatus.failed.value},
    RunStatus.cancelled.value: set(),
    RunStatus.completed.value: set(),
    RunStatus.failed.value: set(),
}

TASK_TRANSITIONS: dict[str, set[str]] = {
    TaskStatus.pending.value: {TaskStatus.assigned.value, TaskStatus.running.value, TaskStatus.blocked.value, TaskStatus.archived.value, TaskStatus.failed.value},
    TaskStatus.assigned.value: {TaskStatus.running.value, TaskStatus.blocked.value, TaskStatus.waiting_collab.value, TaskStatus.waiting_subagent.value, TaskStatus.archived.value, TaskStatus.failed.value},
    TaskStatus.running.value: {TaskStatus.blocked.value, TaskStatus.waiting_collab.value, TaskStatus.waiting_subagent.value, TaskStatus.waiting_review.value, TaskStatus.completed.value, TaskStatus.need_revision.value, TaskStatus.failed.value},
    TaskStatus.blocked.value: {TaskStatus.pending.value, TaskStatus.running.value, TaskStatus.failed.value},
    TaskStatus.waiting_collab.value: {TaskStatus.running.value, TaskStatus.waiting_review.value, TaskStatus.failed.value},
    TaskStatus.waiting_subagent.value: {TaskStatus.running.value, TaskStatus.waiting_review.value, TaskStatus.failed.value},
    TaskStatus.waiting_review.value: {TaskStatus.completed.value, TaskStatus.need_revision.value, TaskStatus.failed.value},
    TaskStatus.need_revision.value: {TaskStatus.running.value, TaskStatus.archived.value, TaskStatus.failed.value},
    TaskStatus.completed.value: {TaskStatus.archived.value},
    TaskStatus.archived.value: set(),
    TaskStatus.failed.value: set(),
}


@dataclass(frozen=True)
class TransitionCheck:
    ok: bool
    reason: str = ""


def check_transition(current: str, target: str, transitions: dict[str, set[str]], allow_same: bool = True) -> TransitionCheck:
    if allow_same and current == target:
        return TransitionCheck(ok=True)
    allowed = transitions.get(current, set())
    if target in allowed:
        return TransitionCheck(ok=True)
    return TransitionCheck(ok=False, reason=f"非法状态流转: {current} -> {target}")


def assert_run_transition(current: str, target: str) -> None:
    result = check_transition(current, target, RUN_TRANSITIONS)
    if not result.ok:
        raise HTTPException(status_code=409, detail=result.reason)


def assert_task_transition(current: str, target: str) -> None:
    result = check_transition(current, target, TASK_TRANSITIONS)
    if not result.ok:
        raise HTTPException(status_code=409, detail=result.reason)


def can_delete_run(status: str) -> bool:
    return status in {RunStatus.created.value, RunStatus.waiting_confirmation.value, *FINAL_RUN_STATUSES}
