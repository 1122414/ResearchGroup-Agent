import uuid
from datetime import datetime

import pytest

from backend.app.services.report_service import ReportService
from backend.app.services.research_state_service import research_state_service
from backend.app.services.thesis_chapter_service import thesis_chapter_service
from backend.app.storage import init_db
from backend.app.storage.repositories import (
    EvidenceRepository, ResearchBriefRepository, ResearchClaimRepository,
    RunRepository, TaskDependencyRepository, TaskRepository,
)


@pytest.fixture(autouse=True)
def _db():
    init_db()


def _insert_task(run_id: str, task_id: str, task_type: str, status: str = "completed") -> dict:
    now = datetime.now().isoformat()
    task = {
        "id": task_id, "run_id": run_id, "title": task_id, "description": "",
        "task_type": task_type, "required_skills": {}, "status": status,
        "created_at": now, "updated_at": now,
    }
    TaskRepository.insert(task)
    return task


def _run_with_thesis(tmp_path, chapters=None) -> tuple[str, dict]:
    now = datetime.now().isoformat()
    run_id = f"run_chapters_{uuid.uuid4().hex[:8]}"
    run = {
        "id": run_id, "research_goal": "完成跨学科硕士论文", "artifact_dir": str(tmp_path / run_id),
        "status": "created", "created_at": now, "updated_at": now,
    }
    RunRepository.insert(run)
    research_state_service.ensure_initialized(run)
    ResearchBriefRepository.update(
        run_id,
        research_question="冻结研究问题如何由真实材料得到回答？",
        objective="完成可追溯硕士论文",
        expected_contribution="形成由真实材料支持的跨学科论证",
        data_availability="材料随工件清单提供",
        discipline={"broad_field": "humanities", "field": "history", "subfield": "intellectual_history"},
        methodology_family="humanities",
        methodology_profile={"family": "humanities", "epistemic_mode": "interpretation"},
        ethics_plan={"required": False, "status": "not_required"},
        thesis_requirements={
            "status": "confirmed", "degree_level": "master", "institution": "测试大学",
            "programme": "历史学", "language": "zh-CN", "citation_style": "Chicago",
            "target_word_count": 3000, "minimum_references": 5, "minimum_supported_claims": 1,
            "required_chapters": chapters or ["引言", "方法", "分析", "结论"],
        },
    )
    return run_id, run


def _chapter_output(name: str, budget: int, claim_id: str) -> dict:
    paragraph = "本段严格依据已经通过审核的研究结论展开解释，并区分材料事实、作者推论、反论证和适用边界。" * 20
    return {
        "summary": f"完成{name}", "claims": [],
        "chapter": {
            "name": name, "word_budget": budget,
            "sections": [{
                "heading": f"{name}核心论证",
                "paragraphs": [
                    {"id": f"{name}_p1", "text": paragraph, "paragraph_type": "claim", "support_ids": [claim_id]},
                    {"id": f"{name}_p2", "text": paragraph, "paragraph_type": "interpretation", "support_ids": [claim_id]},
                    {"id": f"{name}_p3", "text": paragraph, "paragraph_type": "limitation", "support_ids": []},
                ],
            }],
        },
    }


def test_chapter_plan_allocates_declared_total_across_required_chapters():
    plan = thesis_chapter_service.chapter_plan({
        "target_word_count": 30000,
        "required_chapters": ["引言", "文献综述", "方法", "结果", "讨论", "结论"],
    })
    assert len(plan) == 6
    assert sum(item["word_budget"] for item in plan) == pytest.approx(30000, abs=3)
    assert next(item for item in plan if item["chapter_name"] == "文献综述")["word_budget"] > next(
        item for item in plan if item["chapter_name"] == "结论"
    )["word_budget"]


def test_chapter_tasks_are_created_once_and_depend_on_completed_research(tmp_path):
    run_id, _ = _run_with_thesis(tmp_path)
    research = _insert_task(run_id, f"research_{uuid.uuid4().hex[:8]}", "result_analysis")
    report = _insert_task(run_id, f"report_{uuid.uuid4().hex[:8]}", "report_writing", "pending")

    created = thesis_chapter_service.ensure_tasks(run_id)
    repeated = thesis_chapter_service.ensure_tasks(run_id)

    assert len(created) == len(repeated) == 4
    assert {item["id"] for item in created} == {item["id"] for item in repeated}
    assert all(TaskDependencyRepository.get_for_task(item["id"]) == [research["id"]] for item in created)
    assert set(TaskDependencyRepository.get_for_task(report["id"])) == {item["id"] for item in created}


def test_chapter_gate_requires_supported_ids_and_substantive_budget(tmp_path):
    run_id, _ = _run_with_thesis(tmp_path, ["分析"])
    claim_id = f"claim_supported_{uuid.uuid4().hex[:8]}"
    ResearchClaimRepository.insert({
        "id": claim_id, "run_id": run_id, "statement": "冻结史料支持限定解释",
        "status": "supported", "evidence_ids": ["artifact"], "confidence": 0.9,
        "created_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat(),
    })
    task = thesis_chapter_service.ensure_tasks(run_id)[0]
    spec = thesis_chapter_service.spec_from_task(task)
    valid = _chapter_output("分析", spec["word_budget"], claim_id)
    assert thesis_chapter_service.validate_output(task, valid) == []

    invalid = _chapter_output("分析", spec["word_budget"], "invented_claim")
    invalid["chapter"]["sections"][0]["paragraphs"] = invalid["chapter"]["sections"][0]["paragraphs"][:1]
    issues = thesis_chapter_service.validate_output(task, invalid)
    assert any("unknown_support:invented_claim" in issue for issue in issues)
    assert "chapter_paragraph_count_insufficient" in issues


def test_deterministic_thesis_assembly_adds_verified_citations_and_traceability(tmp_path):
    run_id, run = _run_with_thesis(tmp_path, ["分析"])
    claim_id = f"claim_grounded_{uuid.uuid4().hex[:8]}"
    source_id = f"source_{uuid.uuid4().hex[:8]}"
    link_id = f"link_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    ResearchClaimRepository.insert({
        "id": claim_id, "run_id": run_id, "statement": "史料在冻结语境下支持该解释",
        "status": "supported", "evidence_ids": [source_id], "confidence": 0.9,
        "created_at": now, "updated_at": now,
    })
    EvidenceRepository.upsert_source({
        "id": source_id, "run_id": run_id, "title": "Verified Source", "authors": "Author",
        "year": 2024, "venue": "Archive", "url": "https://example.org/source", "source_type": "primary",
        "metadata": {"citation_eligible": True}, "created_at": now,
    })
    EvidenceRepository.insert_link({
        "id": link_id, "run_id": run_id, "claim_id": claim_id, "source_id": source_id,
        "excerpt_id": None, "relation_type": "supports", "confidence": 0.9,
        "rationale": "verified", "created_at": now,
    })
    task = thesis_chapter_service.ensure_tasks(run_id)[0]
    spec = thesis_chapter_service.spec_from_task(task)
    output = _chapter_output("分析", spec["word_budget"], claim_id)
    TaskRepository.update_status(task["id"], "completed", outputs=[output])

    report = thesis_chapter_service.assemble(run, "可追溯硕士论文")

    assert "**交付等级:** `master_thesis_candidate`" in report
    assert "[1]" in report
    assert "Verified Source" in report
    assert f"`{claim_id}`" in report
    assert "## 可追溯附录" in report
    assert "**测试大学**" in report
    assert "## 目录" in report
    assert "## 研究与人工智能来源声明" in report


def test_delivery_status_promotes_only_after_master_thesis_gate():
    report = "# Thesis\n\n**交付等级:** `master_thesis_candidate`"
    assert "`master_thesis`" in ReportService._promote_delivery_status(
        report, {"master_thesis_ready": True}
    )
    assert "`master_thesis_candidate`" in ReportService._promote_delivery_status(
        report, {"master_thesis_ready": False}
    )
