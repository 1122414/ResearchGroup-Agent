from __future__ import annotations

import uuid
from datetime import datetime

from ..core.config import settings
from ..storage.repositories import (
    EvidenceRepository,
    ExperimentFindingRepository,
    ExperimentProtocolRepository,
    ResearchClaimRepository,
    ResearchDecisionRepository,
    ResearchHypothesisRepository,
    ResearchUncertaintyRepository,
    TaskRepository,
)
from .task_graph_service import task_graph_service


class ResearchLoopService:
    """Generate bounded follow-up work from explicit research gaps."""

    def snapshot(self, run_id: str) -> dict:
        claims = ResearchClaimRepository.get_by_run(run_id)
        hypotheses = ResearchHypothesisRepository.get_by_run(run_id)
        uncertainties = ResearchUncertaintyRepository.get_by_run(run_id)
        evidence = EvidenceRepository.get_by_run(run_id)
        protocols = ExperimentProtocolRepository.get_by_run(run_id)
        findings = ExperimentFindingRepository.get_by_run(run_id)
        tasks = TaskRepository.get_all(run_id=run_id)
        loop_tasks = [item for item in tasks if str(item.get("title", "")).startswith("[循环]")]
        loop_rounds = len({item.get("created_at")[:19] for item in loop_tasks})

        gaps: list[dict] = []
        if not evidence["sources"]:
            gaps.append({"kind": "missing_evidence", "reason": "当前还没有已采集证据", "task_type": "literature_survey"})
        if any(item["status"] == "contested" for item in claims):
            gaps.append({"kind": "contested_claim", "reason": "存在仍有争议的 claim", "task_type": "literature_survey"})
        active_hypotheses = [item for item in hypotheses if item["status"] in {"active", "proposed"}]
        protocol_hypothesis_ids = {item["hypothesis_id"] for item in protocols}
        if any(item["id"] not in protocol_hypothesis_ids for item in active_hypotheses):
            gaps.append({"kind": "untested_hypothesis", "reason": "存在尚未被实验检验的 hypothesis", "task_type": "experiment_design"})
        if any(item["status"] == "open" and item["severity"] == "high" for item in uncertainties):
            gaps.append({"kind": "high_uncertainty", "reason": "仍存在高严重度不确定性", "task_type": "literature_survey"})

        supported_claims = [item for item in claims if item["status"] == "supported"]
        stop_reason = ""
        phase = "revision"
        if active_hypotheses and not findings:
            phase = "hypothesis_testing"
        elif gaps:
            phase = "revision"
        elif supported_claims:
            phase = "ready_to_report"
            stop_reason = "已有支持性结论，且当前没有显式研究缺口"
        else:
            phase = "synthesis"
            stop_reason = "没有更多自动化缺口，但也尚未形成强支持结论"

        return {
            "phase": phase,
            "gaps": gaps,
            "loop_rounds": loop_rounds,
            "can_auto_continue": bool(
                settings.research_loop_auto_continue
                and gaps
                and loop_rounds < settings.research_loop_max_auto_rounds
            ),
            "stop_reason": stop_reason,
        }

    def expand_once(self, run_id: str) -> list[dict]:
        snapshot = self.snapshot(run_id)
        if not snapshot["can_auto_continue"]:
            return []

        current_tasks = TaskRepository.get_all(run_id=run_id)
        completed_research_ids = [
            item["id"]
            for item in current_tasks
            if item.get("task_type") != "report_writing" and item.get("status") == "completed"
        ]
        selected = snapshot["gaps"][: settings.research_loop_max_tasks_per_round]
        now = datetime.now().isoformat()
        created: list[dict] = []
        for gap in selected:
            task = self._build_task(run_id, gap, now)
            TaskRepository.insert(task)
            task_graph_service.set_dependencies(task["id"], completed_research_ids)
            created.append(task)

        ResearchDecisionRepository.insert(
            {
                "id": f"decision_{uuid.uuid4().hex[:10]}",
                "run_id": run_id,
                "decision": "启动下一轮研究动作",
                "rationale": "；".join(item["reason"] for item in selected),
                "impact": f"新增 {len(created)} 个由研究缺口驱动的任务",
                "created_at": now,
            }
        )
        return created

    @staticmethod
    def _build_task(run_id: str, gap: dict, now: str) -> dict:
        common = {
            "id": f"task_{uuid.uuid4().hex[:8]}",
            "run_id": run_id,
            "priority": 7,
            "complexity": 5,
            "decomposability": 5,
            "status": "pending",
            "owner_agent": None,
            "collaborator_agents": [],
            "subtasks": [],
            "outputs": [],
            "review_result": None,
            "review_feedback": None,
            "blocked_reason": None,
            "parallelizable": True,
            "is_critical_path": False,
            "attempt_count": 0,
            "last_checkpoint": None,
            "created_at": now,
            "updated_at": now,
        }
        if gap["task_type"] == "experiment_design":
            return {
                **common,
                "title": "[循环] 补充假设验证实验",
                "description": gap["reason"],
                "task_type": "experiment_design",
                "required_skills": {
                    "literature_review": 1,
                    "coding": 5,
                    "experiment": 9,
                    "data_analysis": 7,
                    "academic_writing": 1,
                    "mentoring": 1,
                },
            }
        titles = {
            "missing_evidence": "[循环] 补充基础证据",
            "contested_claim": "[循环] 搜集反证",
            "high_uncertainty": "[循环] 解析高风险不确定性",
        }
        return {
            **common,
            "title": titles.get(gap["kind"], "[循环] 补充反证与缺口证据"),
            "description": gap["reason"],
            "task_type": "literature_survey",
            "required_skills": {
                "literature_review": 9,
                "coding": 1,
                "experiment": 1,
                "data_analysis": 4,
                "academic_writing": 3,
                "mentoring": 1,
            },
        }


research_loop_service = ResearchLoopService()
