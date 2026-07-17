from backend.app.core.config import settings
from backend.app.services.evidence_pipeline_service import evidence_pipeline_service
from backend.app.services.research_loop_critic_service import research_loop_critic_service
from backend.app.services.research_loop_service import research_loop_service
from backend.app.services.run_execution_service import run_execution_service
from backend.app.services.task_recovery_service import task_recovery_service
from backend.app.storage.repositories import (
    ApprovalRequestRepository, EvidenceRepository, ExperimentFindingRepository,
    ExperimentProtocolRepository, ExperimentResultRepository, LLMUsageRepository,
    ResearchBriefRepository, ResearchClaimRepository, ResearchHypothesisRepository,
    ResearchUncertaintyRepository, ReviewDecisionRepository, RunEventRepository, RunRepository,
    TaskRepository,
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


def test_all_research_failed_is_terminal_before_research_loop():
    assert run_execution_service._all_research_failed([
        {"id": "literature", "status": "failed"},
        {"id": "analysis", "status": "failed"},
    ]) is True
    assert run_execution_service._all_research_failed([
        {"id": "literature", "status": "completed"},
        {"id": "analysis", "status": "failed"},
    ]) is False


def test_failed_critical_research_root_blocks_recovery_loop():
    failed = run_execution_service._failed_critical_research_roots([
        {
            "id": "design", "title": "Design", "status": "failed",
            "is_critical_path": True, "revision_of_task_id": None,
        },
        {
            "id": "optional", "title": "[循环R1] supplement", "status": "failed",
            "is_critical_path": False, "revision_of_task_id": None,
        },
        {
            "id": "literature", "title": "Literature", "status": "completed",
            "is_critical_path": True, "revision_of_task_id": None,
        },
    ])

    assert [task["id"] for task in failed] == ["design"]


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


def test_completed_bounded_negative_result_has_no_information_gain():
    gain = research_loop_service._information_gain(
        _state(),
        _state(),
        {"status": "completed", "outputs": [{"insufficient_evidence": True}]},
    )
    assert gain == 0.0


def test_new_unique_citation_counts_as_information_gain():
    gain = research_loop_service._information_gain(
        _state(citation_source_count=2),
        _state(citation_source_count=3),
        {"status": "completed", "outputs": [{}]},
    )
    assert gain == 0.2


def test_quantitative_analysis_satisfies_result_gate_without_experiment(monkeypatch):
    artifact = {
        "family": "quantitative", "input_hashes": ["input-sha"],
        "procedure": "deterministic group comparison", "findings": [{"difference": 0.1}],
        "limitations": ["descriptive only"],
        "method_checks": {
            name: {"status": "passed", "evidence": name}
            for name in ("measurement_validity", "missing_data", "effect_size", "uncertainty", "robustness")
        },
        "artifact": "/tmp/analysis.json", "artifact_sha256": "analysis-sha",
    }
    analysis_task = {
        "id": "analysis_revision", "task_type": "result_analysis", "status": "completed",
        "outputs": [{
            "analysis_artifact": artifact,
            "knowledge_graph": {"claim_ids": ["c1"]},
        }],
        "review_result": {
            "approved": True,
            "quality_gates": {
                "passed": True,
                "layers": {"independent_review": {"passed": True, "simulation": False}},
            },
        },
    }
    brief = {
        "research_type": "empirical", "methodology_family": "quantitative",
        "thesis_requirements": {
            "status": "confirmed", "minimum_supported_claims": 1, "minimum_references": 1,
        },
    }
    monkeypatch.setattr(
        "backend.app.services.research_loop_service.knowledge_graph_service.synchronize_review_status",
        lambda _run_id: None,
    )
    rejected_task = {
        "id": "rejected_search", "task_type": "literature_survey", "status": "need_revision",
        "outputs": [{"knowledge_graph": {"claim_ids": ["rejected_draft"]}}],
        "review_result": {"approved": False},
    }
    monkeypatch.setattr(ResearchClaimRepository, "get_by_run", lambda _run_id: [
        {"id": "c1", "status": "supported"},
        {"id": "rejected_draft", "status": "draft", "statement": "Rejected hallucination"},
    ])
    monkeypatch.setattr(ResearchHypothesisRepository, "get_by_run", lambda _run_id: [])
    monkeypatch.setattr(ResearchUncertaintyRepository, "get_by_run", lambda _run_id: [])
    monkeypatch.setattr(EvidenceRepository, "get_by_run", lambda _run_id: {
        "sources": [{"id": "s1", "url": "https://example.test/source"}],
        "excerpts": [{"id": "p1", "source_id": "s1"}],
        "links": [{"claim_id": "c1", "source_id": "s1", "relation_type": "supports"}],
    })
    monkeypatch.setattr(ExperimentResultRepository, "get_by_run", lambda _run_id: [])
    monkeypatch.setattr(ResearchBriefRepository, "get_by_run", lambda _run_id: brief)
    monkeypatch.setattr(TaskRepository, "get_all", lambda run_id=None: [analysis_task, rejected_task])
    monkeypatch.setattr(ReviewDecisionRepository, "get_by_run", lambda _run_id: [
        {"task_id": "analysis_revision", "approved": True},
        {"task_id": "rejected_search", "approved": False},
    ])
    monkeypatch.setattr(ExperimentProtocolRepository, "get_by_run", lambda _run_id: [])
    monkeypatch.setattr(ExperimentFindingRepository, "get_by_run", lambda _run_id: [])
    monkeypatch.setattr(RunRepository, "get_by_id", lambda _run_id: None)
    monkeypatch.setattr(research_loop_service, "_loop_usage_summary", lambda _run_id: {
        "total_tokens": 0, "total_cost_usd": 0.0,
    })

    state = research_loop_service._state("run_quantitative")

    assert state["publishable_experiment_count"] == 0
    assert state["verified_analysis_count"] == 1
    assert state["claim_count"] == 1
    assert state["staged_claim_count"] == 1
    assert state["claim_coverage"] == 1.0
    assert state["result_evidence_requirement"] == "verified_analysis"
    assert state["method_result_ready"] is True
    assert state["ready_to_report"] is True
    gaps, human = research_loop_service._gaps("run_quantitative", state)
    assert gaps == []
    assert human == []

    analysis_task["review_result"]["quality_gates"]["layers"]["independent_review"]["simulation"] = True
    blocked = research_loop_service._state("run_quantitative")
    assert blocked["verified_analysis_count"] == 0
    assert blocked["ready_to_report"] is False


def test_duplicate_source_ids_with_same_url_count_once():
    sources = [
        {"id": "attachment_source_1", "title": "Dataset", "url": "https://example.org/data?a=1", "metadata": {}},
        {"id": "source_2", "title": "Dataset", "url": "https://example.org/data?a=2", "metadata": {"canonical_id": "attachment_source_1"}},
    ]
    assert research_loop_service._unique_source_count(sources) == 1


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


def test_loop_action_family_is_single_shot_and_budget_visible(monkeypatch):
    root = {"id": "loop", "title": "[循环R1] 补足证据", "run_id": "run_loop"}
    revision = {
        "id": "revision", "title": "返工：补足证据", "run_id": "run_loop",
        "revision_of_task_id": "loop",
    }
    monkeypatch.setattr(TaskRepository, "get_by_id", lambda task_id: root if task_id == "loop" else None)

    assert research_loop_service.is_loop_task(root) is True
    assert research_loop_service.is_loop_task(revision) is True
    assert task_recovery_service.can_create_revision(root) is False
    assert task_recovery_service.create_revision_task(root, "仍需补证") is None


def test_research_loop_selects_at_most_one_action_per_tool():
    actions = [
        {"id": "coverage", "selected_tool": "evidence_search"},
        {"id": "uncertainty", "selected_tool": "evidence_search"},
        {"id": "experiment", "selected_tool": "experiment_runner"},
    ]

    selected = research_loop_service._select_diverse_actions(actions, 3)

    assert [item["id"] for item in selected] == ["coverage", "experiment"]


def test_research_loop_actions_never_depend_on_writing_tasks():
    tasks = [
        {"id": "research", "task_type": "literature_survey", "status": "completed"},
        {"id": "analysis", "task_type": "result_analysis", "status": "completed"},
        {"id": "chapter", "task_type": "thesis_chapter", "status": "completed"},
        {"id": "report", "task_type": "report_writing", "status": "completed"},
    ]

    assert research_loop_service._research_dependencies(tasks) == ["research", "analysis"]


def test_run_executor_uses_isolated_research_loop_budget():
    assert "get_summary" not in __import__("inspect").getsource(
        run_execution_service._execute_one_task
    )
    assert "_loop_usage_summary" in __import__("inspect").getsource(
        run_execution_service._execute_one_task
    )


def test_execution_progress_distinguishes_pending_revision_attempts():
    before = [{"id": "chapter", "status": "pending", "attempt_count": 5}]
    after = [{"id": "chapter", "status": "pending", "attempt_count": 6}]

    assert run_execution_service._execution_progress(before) != (
        run_execution_service._execution_progress(after)
    )


def test_task_event_guards_use_exact_unbounded_count(monkeypatch):
    calls = []
    monkeypatch.setattr(
        RunEventRepository, "count_task_events",
        lambda run_id, task_id, event_type: calls.append((run_id, task_id, event_type)) or 2,
    )
    task = {"id": "chapter", "run_id": "run"}

    assert run_execution_service._has_task_event(task, "revision.once") is True
    assert run_execution_service._task_event_count(task, "revision.once") == 2
    assert calls == [
        ("run", "chapter", "revision.once"),
        ("run", "chapter", "revision.once"),
    ]


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


def test_stuck_old_revision_cannot_fail_completed_family_descendants(monkeypatch):
    tasks = [
        {"id": "root", "revision_of_task_id": None, "status": "completed"},
        {"id": "old", "revision_of_task_id": "root", "status": "need_revision"},
        {"id": "new", "revision_of_task_id": "root", "status": "completed"},
        {"id": "descendant", "revision_of_task_id": None, "status": "blocked"},
    ]
    by_id = {item["id"]: item for item in tasks}
    failed_descendants = []
    monkeypatch.setattr(TaskRepository, "get_all", lambda run_id=None: tasks)
    monkeypatch.setattr(TaskRepository, "get_by_id", lambda task_id: by_id.get(task_id))
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda task_id, status, **fields: by_id[task_id].update(status=status, **fields),
    )
    monkeypatch.setattr(
        run_execution_service, "_fail_dependency_descendants",
        lambda *args: failed_descendants.append(args),
    )

    assert run_execution_service._finalize_stuck_revisions("run_loop", tasks) is True
    assert by_id["old"]["status"] == "archived"
    assert by_id["descendant"]["status"] == "blocked"
    assert failed_descendants == []


def test_restart_revives_only_descendants_failed_by_superseded_revision(monkeypatch):
    tasks = [
        {"id": "root", "status": "completed", "revision_of_task_id": None},
        {"id": "revision", "status": "completed", "revision_of_task_id": "root"},
        {"id": "legacy_desc", "status": "failed", "blocked_reason": "前置任务失败，无法继续：旧返工耗尽"},
        {"id": "real_failure", "status": "failed", "blocked_reason": "实验复现失败"},
    ]
    by_id = {item["id"]: item for item in tasks}
    monkeypatch.setattr(TaskRepository, "get_all", lambda run_id=None: tasks)
    monkeypatch.setattr(TaskRepository, "get_by_id", lambda task_id: by_id.get(task_id))
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda task_id, status, **fields: by_id[task_id].update(status=status, **fields),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.task_graph_service.descendants",
        lambda _run_id, _root_id: ["legacy_desc", "real_failure"],
    )

    assert run_execution_service._recover_superseded_revision_failures("run_loop") == 1
    assert by_id["legacy_desc"]["status"] == "pending"
    assert by_id["real_failure"]["status"] == "failed"


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


def test_thesis_in_place_revision_remains_bounded_while_allowing_issue_reduction(monkeypatch):
    task = {"task_type": "thesis_chapter", "attempt_count": 1}
    assert run_execution_service._can_reopen_thesis_in_place(task) is True
    assert run_execution_service._can_reopen_thesis_in_place({**task, "attempt_count": 4}) is True
    assert run_execution_service._can_reopen_thesis_in_place({**task, "attempt_count": 5}) is False
    assert run_execution_service._can_reopen_thesis_in_place({**task, "task_type": "literature_survey"}) is False

    audit_review = {
        "quality_gates": {"layers": {"independent_review": {
            "reviewer": "independent_reviewer_model_paragraph_audit",
        }}},
    }
    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: False)
    assert run_execution_service._can_reopen_thesis_in_place(
        {**task, "id": "chapter", "run_id": "run", "attempt_count": 5}, audit_review,
    ) is True
    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: True)
    assert run_execution_service._can_reopen_thesis_in_place(
        {**task, "id": "chapter", "run_id": "run", "attempt_count": 5}, audit_review,
    ) is False


def test_first_exhaustive_paragraph_audit_can_recheck_existing_output_once(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 5, "owner_agent": "writer",
        "review_result": {"quality_gates": {"layers": {"independent_review": {
            "reviewer": "independent_reviewer_model_paragraph_audit",
        }}}},
    }
    events = []

    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: False)
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda _task_id, status, **fields: task.update(status=status, **fields),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_first_paragraph_audit([task]) is True
    assert task["status"] == "running"
    assert task["attempt_count"] == 5
    assert events == ["review.paragraph_audit_recheck"]


def test_legacy_chapter_gets_one_final_rewrite_after_structural_floor_migration(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 6, "owner_agent": "writer",
        "review_result": {"quality_gates": {"layers": {"independent_review": {
            "reviewer": "independent_reviewer_model_paragraph_audit",
        }}}},
    }
    events = []

    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: False)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.task_recovery_service.reopen_thesis_in_place",
        lambda item, _review: {**item, "status": "pending"},
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_structural_floor_migration([task]) is True
    assert task["attempt_count"] == 6
    assert events == ["revision.structural_floor_migration"]

    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: True)
    assert run_execution_service._retry_structural_floor_migration([task]) is False


def test_surgical_repair_reuses_output_without_increasing_attempt(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 7, "owner_agent": "writer",
        "revision_of_task_id": "root", "title": "Introduction",
        "outputs": [{"summary": "old", "chapter": {}}],
        "review_result": {"quality_gates": {"layers": {"independent_review": {
            "reviewer": "independent_reviewer_model_paragraph_audit",
        }}}},
    }
    persisted = []
    events = []
    repaired_result = {"summary": "surgical", "chapter": {}}

    monkeypatch.setattr(run_execution_service, "_task_event_count", lambda *_args: 0)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.surgical_repair",
        lambda *_args: {
            "result": repaired_result,
            "changes": [{"target": "p1", "operation": "delete"}],
            "unresolved": [],
        },
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda _task_id, status, **fields: task.update(status=status, **fields),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.OutputRepository.insert",
        lambda output: persisted.append(output),
    )
    monkeypatch.setattr(run_execution_service, "_revive_dependency_descendants", lambda *_args: None)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_surgical_chapter_repair([task]) is True
    assert task["status"] == "running"
    assert task["attempt_count"] == 7
    assert task["outputs"] == [repaired_result]
    assert persisted[0]["id"] == "out_chapter"
    assert events == ["revision.surgical_chapter_repair"]


def test_restored_chapter_gets_only_one_separate_v2_surgical_pass(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 7, "owner_agent": "writer",
        "outputs": [{"summary": "restored", "chapter": {}}],
        "review_result": {"quality_gates": {"layers": {"independent_review": {
            "reviewer": "independent_reviewer_model_paragraph_audit_v2",
        }}}},
    }
    events = []

    monkeypatch.setattr(run_execution_service, "_task_event_count", lambda *_args: 5)
    monkeypatch.setattr(
        run_execution_service, "_has_task_event",
        lambda _task, event: event == "revision.advisor_paragraph_restoration",
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.surgical_repair",
        lambda *_args: {
            "result": {"summary": "cleaned", "chapter": {}},
            "changes": [{"target": "p1", "operation": "delete"}], "unresolved": [],
        },
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.word_count",
        lambda *_args: 600,
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda _task_id, status, **fields: task.update(status=status, **fields),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.OutputRepository.insert", lambda _output: None,
    )
    monkeypatch.setattr(run_execution_service, "_revive_dependency_descendants", lambda *_args: None)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_surgical_chapter_repair([task]) is True
    assert task["status"] == "running"
    assert events == ["revision.post_restoration_surgical_repair"]

    task["status"] = "failed"
    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: True)
    assert run_execution_service._retry_surgical_chapter_repair([task]) is False


def test_exhausted_v2_surgery_can_use_one_global_editorial_pass(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 6, "owner_agent": "writer",
        "outputs": [{"summary": "audited", "chapter": {}}],
        "review_result": {"quality_gates": {"layers": {"independent_review": {
            "reviewer": "independent_reviewer_model",
        }}}},
    }
    events = []
    monkeypatch.setattr(run_execution_service, "_task_event_count", lambda *_args: 5)
    monkeypatch.setattr(
        run_execution_service, "_has_task_event",
        lambda _task, event: event == "revision.paragraph_audit_consolidation",
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.editorial_repair",
        lambda *_args: {
            "result": {"summary": "edited", "chapter": {}},
            "changes": [{"target": "p1", "operation": "clean_punctuation"}],
        },
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.word_count",
        lambda *_args: 600,
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda _task_id, status, **fields: task.update(status=status, **fields),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.OutputRepository.insert", lambda _output: None,
    )
    monkeypatch.setattr(run_execution_service, "_revive_dependency_descendants", lambda *_args: None)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_surgical_chapter_repair([task]) is True
    assert events == ["revision.global_editorial_repair"]


def test_global_editorial_pass_allows_one_followup_evidence_repair(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 6, "owner_agent": "writer",
        "outputs": [{"summary": "edited", "chapter": {}}],
        "review_result": {"quality_gates": {"layers": {"independent_review": {
            "reviewer": "independent_reviewer_model_paragraph_audit_v2",
        }}}},
    }
    events = []
    monkeypatch.setattr(run_execution_service, "_task_event_count", lambda *_args: 5)
    monkeypatch.setattr(
        run_execution_service, "_has_task_event",
        lambda _task, event: event == "revision.global_editorial_repair",
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.surgical_repair",
        lambda *_args: {
            "result": {"summary": "evidence-clean", "chapter": {}},
            "changes": [{"target": "p1", "operation": "delete"}], "unresolved": [],
        },
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.word_count",
        lambda *_args: 600,
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda _task_id, status, **fields: task.update(status=status, **fields),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.OutputRepository.insert", lambda _output: None,
    )
    monkeypatch.setattr(run_execution_service, "_revive_dependency_descendants", lambda *_args: None)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_surgical_chapter_repair([task]) is True
    assert events == ["revision.post_editorial_evidence_repair"]


def test_frozen_method_contract_migration_is_bounded(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 7, "owner_agent": "writer",
        "outputs": [{"summary": "old", "chapter": {}}],
        "review_result": {"quality_gates": {"layers": {"independent_review": {
            "reviewer": "independent_reviewer_model_paragraph_audit_v2",
            "issues": [{"target": "p1", "reason": "token unit mismatch", "required_change": "use characters"}],
        }}}},
    }
    events = []
    monkeypatch.setattr(run_execution_service, "_task_event_count", lambda *_args: 5)
    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: False)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.surgical_repair",
        lambda *_args: {
            "result": {"summary": "fixed", "chapter": {}},
            "changes": [{"target": "p1", "operation": "replace_verified"}], "unresolved": [],
        },
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.word_count", lambda *_args: 600,
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda _task_id, status, **fields: task.update(status=status, **fields),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.OutputRepository.insert", lambda _output: None,
    )
    monkeypatch.setattr(run_execution_service, "_revive_dependency_descendants", lambda *_args: None)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_surgical_chapter_repair([task]) is True
    assert events == ["revision.frozen_method_contract_migration"]


def test_v3_global_exact_issue_gets_one_bounded_repair(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 7, "owner_agent": "writer",
        "outputs": [{"chapter": {}}],
        "review_result": {"quality_gates": {"layers": {"independent_review": {
            "reviewer": "independent_reviewer_model_paragraph_audit_v3_global",
            "issues": [{"target": "scope", "reason": "‘exact phrase’ extrapolates", "required_change": "删除该句"}],
        }}}},
    }
    events = []
    monkeypatch.setattr(run_execution_service, "_task_event_count", lambda *_args: 5)
    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: False)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.surgical_repair",
        lambda *_args: {
            "result": {"chapter": {}}, "changes": [{"target": "p1", "operation": "delete"}],
            "unresolved": [],
        },
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.word_count", lambda *_args: 500,
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda _task_id, status, **fields: task.update(status=status, **fields),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.OutputRepository.insert", lambda _output: None,
    )
    monkeypatch.setattr(run_execution_service, "_revive_dependency_descendants", lambda *_args: None)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_surgical_chapter_repair([task]) is True
    assert events == ["revision.v3_global_exact_repair"]


def test_late_support_binding_requires_every_issue_to_name_verified_style_id(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 7, "owner_agent": "writer",
        "outputs": [{"chapter": {}}],
        "review_result": {"quality_gates": {"layers": {"independent_review": {
            "reviewer": "independent_reviewer_model_paragraph_audit_v2",
            "issues": [{
                "target": "p1", "reason": "support available",
                "required_change": "bind experiment:verified to p1",
            }],
        }}}},
    }
    events = []
    monkeypatch.setattr(run_execution_service, "_task_event_count", lambda *_args: 5)
    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: False)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.surgical_repair",
        lambda *_args: {
            "result": {"chapter": {}},
            "changes": [{"target": "p1", "operation": "bind", "support_ids": ["experiment:verified"]}],
            "unresolved": [],
        },
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.word_count", lambda *_args: 500,
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda _task_id, status, **fields: task.update(status=status, **fields),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.OutputRepository.insert", lambda _output: None,
    )
    monkeypatch.setattr(run_execution_service, "_revive_dependency_descendants", lambda *_args: None)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_surgical_chapter_repair([task]) is True
    assert events == ["revision.late_support_binding"]


def test_legacy_direct_entailment_audit_rechecks_without_spending_surgical_round(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 7, "owner_agent": "writer",
        "revision_of_task_id": "root", "title": "Introduction",
        "outputs": [{"summary": "old", "chapter": {}}],
        "review_result": {"quality_gates": {"layers": {"independent_review": {
            "reviewer": "independent_reviewer_model_paragraph_audit",
        }}}},
    }
    events = []

    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: False)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.surgical_repair",
        lambda *_args: {"result": {"summary": "clean"}, "changes": [], "unresolved": []},
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda _task_id, status, **fields: task.update(status=status, **fields),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.OutputRepository.insert", lambda _output: None,
    )
    monkeypatch.setattr(run_execution_service, "_revive_dependency_descendants", lambda *_args: None)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_epistemic_audit_migration([task]) is True
    assert task["status"] == "running"
    assert task["attempt_count"] == 7
    assert events == ["review.epistemic_audit_migration"]


def test_advisor_restoration_reuses_persisted_text_and_reopens_review(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 7, "owner_agent": "writer",
        "revision_of_task_id": "root", "title": "Introduction",
        "outputs": [{"summary": "current", "chapter": {}}],
        "review_result": {
            "feedback": "请恢复 p1",
            "quality_gates": {"passed": True},
        },
    }
    events = []

    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: False)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.restore_reviewed_paragraphs",
        lambda *_args: {
            "result": {"summary": "restored", "chapter": {}},
            "changes": [{"target": "p1", "operation": "restore_previous_exact"}],
        },
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda _task_id, status, **fields: task.update(status=status, **fields),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.OutputRepository.insert", lambda _output: None,
    )
    monkeypatch.setattr(run_execution_service, "_revive_dependency_descendants", lambda *_args: None)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_advisor_paragraph_restoration([task]) is True
    assert task["status"] == "running"
    assert task["attempt_count"] == 7
    assert events == ["revision.advisor_paragraph_restoration"]


def test_passed_gate_advisor_exact_cleanup_reopens_without_attempt(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 7, "owner_agent": "writer",
        "outputs": [{"summary": "old", "chapter": {}}],
        "review_result": {
            "feedback": "请从 p1 删除 ‘unsupported sentence’",
            "quality_gates": {"passed": True},
        },
    }
    events = []
    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: False)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.advisor_exact_cleanup",
        lambda *_args: {
            "result": {"summary": "clean", "chapter": {}},
            "changes": [{"target": "p1", "operation": "delete"}], "unresolved": [],
        },
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda _task_id, status, **fields: task.update(status=status, **fields),
    )
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.OutputRepository.insert", lambda _output: None,
    )
    monkeypatch.setattr(run_execution_service, "_revive_dependency_descendants", lambda *_args: None)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_advisor_exact_cleanup([task]) is True
    assert task["status"] == "running"
    assert task["attempt_count"] == 7
    assert events == ["revision.advisor_exact_cleanup"]


def test_v2_global_failure_rechecks_once_under_balanced_scope(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 7, "owner_agent": "writer",
        "revision_of_task_id": "root", "outputs": [{"chapter": {}}],
        "review_result": {"quality_gates": {"layers": {"independent_review": {
            "reviewer": "independent_reviewer_model_paragraph_audit_v2_global",
        }}}},
    }
    events = []
    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: False)
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda _task_id, status, **fields: task.update(status=status, **fields),
    )
    monkeypatch.setattr(run_execution_service, "_revive_dependency_descendants", lambda *_args: None)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_global_scope_migration([task]) is True
    assert task["status"] == "running"
    assert task["attempt_count"] == 7
    assert events == ["review.global_scope_migration"]


def test_persisted_advisor_artifact_conflict_rechecks_once(monkeypatch):
    task = {
        "id": "chapter", "run_id": "run", "task_type": "thesis_chapter",
        "status": "failed", "attempt_count": 7, "owner_agent": "writer",
        "revision_of_task_id": "root", "outputs": [{"chapter": {}}],
        "review_result": {"feedback": "characters 应改为 tokens", "quality_gates": {"passed": True}},
    }
    events = []
    monkeypatch.setattr(run_execution_service, "_has_task_event", lambda *_args: False)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.thesis_chapter_service.advisor_feedback_conflicts_with_artifact",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        TaskRepository, "update_status",
        lambda _task_id, status, **fields: task.update(status=status, **fields),
    )
    monkeypatch.setattr(run_execution_service, "_revive_dependency_descendants", lambda *_args: None)
    monkeypatch.setattr(
        "backend.app.services.run_execution_service.run_event_service.emit",
        lambda _run_id, event_type, *_args, **_kwargs: events.append(event_type),
    )

    assert run_execution_service._retry_advisor_artifact_conflict_migration([task]) is True
    assert task["status"] == "running"
    assert task["attempt_count"] == 7
    assert events == ["review.advisor_artifact_conflict_migration"]
