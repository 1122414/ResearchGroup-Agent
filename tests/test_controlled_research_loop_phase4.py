from backend.app.core.config import settings
from backend.app.services.evidence_pipeline_service import evidence_pipeline_service
from backend.app.services.research_loop_critic_service import research_loop_critic_service
from backend.app.services.research_loop_service import research_loop_service
from backend.app.services.run_execution_service import run_execution_service
from backend.app.storage.repositories import (
    ApprovalRequestRepository, LLMUsageRepository, RunEventRepository, RunRepository, TaskRepository,
)


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


def test_thesis_contract_creates_evidence_coverage_gap_without_lowering_thresholds():
    brief = {"thesis_requirements": {
        "status": "confirmed", "minimum_supported_claims": 5, "minimum_references": 5,
    }}

    gap = research_loop_service._thesis_evidence_gap(
        brief, _state(supported_claim_count=3, citation_source_count=2),
    )

    assert gap["kind"] == "thesis_evidence_coverage"
    assert "3/5" in gap["reason"]
    assert "2/5" in gap["reason"]
    assert research_loop_service._thesis_evidence_gap(
        brief, _state(supported_claim_count=5, citation_source_count=5),
    ) is None


def test_research_loop_budget_excludes_writing_and_includes_loop_revisions(monkeypatch):
    monkeypatch.setattr(TaskRepository, "get_all", lambda run_id=None: [
        {"id": "research", "title": "initial research", "revision_of_task_id": None},
        {"id": "loop", "title": "[循环R1] evidence coverage", "revision_of_task_id": None},
        {"id": "loop_revision", "title": "返工 loop", "revision_of_task_id": "loop"},
        {"id": "chapter", "title": "thesis chapter", "revision_of_task_id": None},
    ])
    monkeypatch.setattr(LLMUsageRepository, "get_by_run", lambda _run_id: [
        {"task_id": "research", "total_tokens": 100, "cost_usd": 1.0},
        {"task_id": "loop", "total_tokens": 20, "cost_usd": 0.2},
        {"task_id": "loop_revision", "total_tokens": 30, "cost_usd": 0.3},
        {"task_id": "chapter", "total_tokens": 1000, "cost_usd": 10.0},
    ])

    assert research_loop_service._loop_usage_summary("run_loop") == {
        "total_tokens": 50, "total_cost_usd": 0.5,
    }


def test_run_executor_uses_isolated_research_loop_budget():
    assert "get_summary" not in __import__("inspect").getsource(
        run_execution_service._execute_one_task
    )
    assert "_loop_usage_summary" in __import__("inspect").getsource(
        run_execution_service._execute_one_task
    )


def test_action_contract_is_not_mixed_into_search_query(monkeypatch):
    monkeypatch.setattr(RunRepository, "get_by_id", lambda _run_id: None)
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


def test_search_query_keeps_original_research_question(monkeypatch):
    monkeypatch.setattr(RunRepository, "get_by_id", lambda _run_id: {
        "research_goal": "Compare overlapping passage segmentation on MRR.\n\n## 用户上传的多模态附件上下文\nattachment context",
    })
    monkeypatch.setattr(TaskRepository, "get_by_id", lambda _task_id: None)
    query = evidence_pipeline_service._query_for_task({
        "id": "task_lit", "run_id": "run_1", "title": "核验文献",
        "description": "检索全文并验证来源",
    })

    assert "Compare overlapping passage segmentation on MRR" in query
    assert "attachment context" not in query


def test_frozen_scope_limitations_do_not_trigger_research_loop():
    uncertainties = [
        {"id": "u1", "status": "open", "severity": "high", "description": "Generalizability to other corpora is unknown."},
        {"id": "u2", "status": "open", "severity": "high", "description": "当前来源未直接测试重叠分割对 MRR 的影响。"},
        {"id": "u3", "status": "open", "severity": "high", "description": "输入文件哈希尚未核验。"},
    ]

    assert research_loop_service._actionable_high_uncertainties(uncertainties, True) == [uncertainties[2]]
    assert research_loop_service._is_scope_boundary("multi-domain benchmark domain mismatch") is True
    assert research_loop_service._is_scope_boundary("该结论在更大规模、更自然的语料上是否成立仍未知") is True
    assert research_loop_service._is_scope_boundary("pilot的均匀效应是否在更大、更多样化的数据集上持续存在未知") is True
    assert research_loop_service._is_scope_boundary("当前冻结数据集的输入哈希尚未核验") is False


def test_supported_cross_language_hypothesis_is_not_retested():
    proposed = {"statement": "固定重叠分割相比无分割基线能提升 MRR 至少 5%。"}
    supported = {"statement": "Fixed overlapping segmentation improves MRR over the no-split baseline by at least 5%."}

    assert research_loop_service._same_hypothesis(proposed, supported) is True


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


def test_failed_required_chapter_blocks_thesis_assembly_but_failed_sibling_does_not():
    tasks = [
        {"id": "chapter_method", "title": "Methodology", "task_type": "thesis_chapter", "status": "failed"},
        {"id": "chapter_discussion", "title": "Discussion", "task_type": "thesis_chapter", "status": "blocked"},
        {
            "id": "old_revision", "task_type": "thesis_chapter", "status": "failed",
            "revision_of_task_id": "chapter_results",
        },
        {"id": "chapter_results", "task_type": "thesis_chapter", "status": "completed"},
    ]

    failed = run_execution_service._failed_required_chapters(tasks)

    assert [task["id"] for task in failed] == ["chapter_method", "chapter_discussion"]


def test_completed_chapter_with_invalid_resolved_output_still_blocks_assembly(monkeypatch):
    chapter = {"id": "chapter_short", "status": "completed", "outputs": [{"chapter": {}}]}
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.resolved_chapters",
        lambda _run_id: [chapter],
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.validate_output",
        lambda *_args: ["chapter_word_count_below_contract_minimum:600/900/1000"],
    )

    assert run_execution_service._invalid_required_chapters("run_loop") == [chapter]
