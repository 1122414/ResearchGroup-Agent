from backend.app.core.config import settings
from backend.app.services.evidence_pipeline_service import evidence_pipeline_service
from backend.app.services.research_loop_critic_service import research_loop_critic_service
from backend.app.services.research_loop_service import research_loop_service
from backend.app.services.run_execution_service import run_execution_service
from backend.app.storage.repositories import ApprovalRequestRepository, RunEventRepository, TaskRepository


def _state(**updates):
    state = {
        "source_count": 1, "passage_count": 1, "claim_count": 1,
        "supported_claim_count": 0, "contested_claim_count": 1,
        "active_hypothesis_count": 0, "publishable_experiment_count": 0,
        "high_uncertainty_count": 0, "claim_coverage": 0.0,
        "total_tokens": 0, "total_cost_usd": 0.0,
        "minimum_information_gain": 0.05, "signature": "state-v1", "ready_to_report": False,
    }
    state.update(updates)
    return state


def test_independent_critic_rejects_duplicate_and_unready_experiment():
    candidate = research_loop_service._candidate(
        {
            "kind": "untested_hypothesis", "target_id": "hyp_1", "reason": "test hypothesis",
            "task_type": "experiment_design", "expected_information_gain": 0.9, "dataset_ready": False,
        },
        _state(),
        1,
    )
    result = research_loop_critic_service.review(candidate, {candidate["fingerprint"]}, _state())
    assert result["approved"] is False
    assert "duplicate_action" in result["reasons"]
    assert "experiment_dataset_not_ready" in result["reasons"]
    assert result["reviewer"] == "deterministic_independent_critic_v1"


def test_snapshot_stops_instead_of_repeating_same_action(monkeypatch):
    gap = {
        "kind": "contested_claim", "target_id": "claim_1", "reason": "search counter evidence",
        "task_type": "literature_survey", "expected_information_gain": 0.8, "dataset_ready": False,
    }
    candidate = research_loop_service._candidate(gap, _state(), 2)
    monkeypatch.setattr(research_loop_service, "_state", lambda _run_id: _state())
    monkeypatch.setattr(research_loop_service, "_gaps", lambda _run_id, _snapshot: ([gap], []))
    monkeypatch.setattr(
        RunEventRepository,
        "get_by_run",
        lambda *_args, **_kwargs: [{
            "event_type": "research_loop.action_selected",
            "payload": {"round": 1, "action": {"fingerprint": candidate["fingerprint"]}},
        }],
    )
    monkeypatch.setattr(settings, "research_loop_max_auto_rounds", 3)

    snapshot = research_loop_service.snapshot("run_loop")

    assert snapshot["can_auto_continue"] is False
    assert snapshot["terminal_state"] == "incomplete"
    assert "已执行过" in snapshot["stop_reason"]


def test_completed_bounded_negative_result_counts_as_small_information_gain():
    gain = research_loop_service._information_gain(
        _state(),
        _state(),
        {"status": "completed", "outputs": [{"insufficient_evidence": True}]},
    )
    assert gain == 0.05


def test_action_contract_is_not_mixed_into_search_query():
    action = {
        "id": "action_1", "round": 1, "objective": "核验目标 claim", "target": {"type": "claim", "id": "c1"},
        "selected_tool": "evidence_search", "arguments": {}, "expected_observation": "new passage",
        "success_condition": "claim changes", "failure_handling": "stop", "budget": {"max_tokens": 1000},
        "safety_level": "low", "provenance": {}, "fingerprint": "fp1", "expected_information_gain": 0.8,
        "critic": {"approved": True},
    }
    task = research_loop_service._build_task(
        "run_1", action, "2026-07-14T00:00:00", {"subquestion_id": None, "hypothesis_id": None, "milestones": {}},
    )
    query = evidence_pipeline_service._query_for_task(task)
    assert "核验目标 claim" in query
    assert "max_tokens" not in query
    assert "fingerprint" not in query


def test_approved_research_loop_intervention_is_reused(monkeypatch):
    monkeypatch.setattr(
        ApprovalRequestRepository,
        "get_by_run",
        lambda _run_id: [{
            "request_type": "research_loop_intervention",
            "task_id": None,
            "status": "approved",
        }],
    )

    assert run_execution_service._approved("run_loop", "research_loop_intervention") is True


def test_completed_revision_archives_older_failed_drafts(monkeypatch):
    tasks = [
        {"id": "old", "revision_of_task_id": "root", "status": "need_revision"},
        {"id": "new", "revision_of_task_id": "root", "status": "completed"},
        {"id": "other", "revision_of_task_id": "other_root", "status": "need_revision"},
    ]
    updates = []
    monkeypatch.setattr(TaskRepository, "get_all", lambda run_id=None: tasks)
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda task_id, status, **fields: updates.append((task_id, status, fields)),
    )

    run_execution_service._archive_superseded_revisions("run_loop")

    assert [(task_id, status) for task_id, status, _fields in updates] == [("old", "archived")]
