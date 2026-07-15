from __future__ import annotations

import uuid
from datetime import datetime

from ..core.research_goal import primary_goal
from ..storage.repositories import (
    ResearchBriefRepository,
    ResearchClaimRepository,
    ResearchDecisionRepository,
    ResearchHypothesisRepository,
    ResearchMilestoneRepository,
    ResearchUncertaintyRepository,
)


class ResearchStateService:
    def ensure_initialized(self, run: dict) -> None:
        if ResearchBriefRepository.get_by_run(run["id"]):
            return

        now = datetime.now().isoformat()
        question = primary_goal(str(run.get("research_goal", ""))).strip()
        ResearchBriefRepository.insert(
            {
                "id": f"brief_{uuid.uuid4().hex[:10]}",
                "run_id": run["id"],
                "research_question": question,
                "objective": question,
                "scope": "",
                "success_criteria": [
                    "澄清研究问题、边界与评价标准",
                    "形成可追溯的证据链",
                    "输出明确区分结论与未决问题的阶段性结果",
                ],
                "constraints": [],
                "research_type": "empirical",
                "subquestions": [],
                "scope_in": [],
                "scope_out": [],
                "target_domain": "",
                "expected_contribution": "",
                "novelty_criteria": [],
                "data_availability": "",
            "ethics_risks": [],
            "failure_criteria": [],
            "discipline": {},
            "methodology_family": "",
            "epistemic_mode": "",
            "methodology_profile": {},
            "resource_plan": [],
            "ethics_plan": {},
            "thesis_requirements": {},
            "feasibility_assessment": {},
                "approval_status": "draft",
                "validation_errors": [],
                "status": "draft",
                "created_at": now,
                "updated_at": now,
            }
        )
        ResearchDecisionRepository.insert(
            {
                "id": f"decision_{uuid.uuid4().hex[:10]}",
                "run_id": run["id"],
                "decision": "先建立研究问题与证据边界，再进入任务拆解。",
                "rationale": "避免系统直接从任务流跳到结论，保留后续证据更新和方案调整空间。",
                "impact": "后续任务、证据和报告都应回挂到研究状态对象。",
                "created_at": now,
            }
        )
        ResearchUncertaintyRepository.insert(
            {
                "id": f"uncertainty_{uuid.uuid4().hex[:10]}",
                "run_id": run["id"],
                "description": "尚未形成经过证据支撑的可验证假设。",
                "category": "hypothesis",
                "severity": "high",
                "status": "open",
                "created_at": now,
                "resolved_at": None,
            }
        )

    def get_state(self, run_id: str) -> dict:
        return {
            "brief": ResearchBriefRepository.get_by_run(run_id),
            "hypotheses": ResearchHypothesisRepository.get_by_run(run_id),
            "claims": ResearchClaimRepository.get_by_run(run_id),
            "decisions": ResearchDecisionRepository.get_by_run(run_id),
            "uncertainties": ResearchUncertaintyRepository.get_by_run(run_id),
            "milestones": ResearchMilestoneRepository.get_by_run(run_id),
        }

    def summary(self, run_id: str) -> dict:
        state = self.get_state(run_id)
        uncertainties = state["uncertainties"]
        return {
            "has_brief": bool(state["brief"]),
            "research_type": (state["brief"] or {}).get("research_type"),
            "discipline": (state["brief"] or {}).get("discipline", {}),
            "methodology_family": (state["brief"] or {}).get("methodology_family"),
            "epistemic_mode": (state["brief"] or {}).get("epistemic_mode"),
            "research_ready": ((state["brief"] or {}).get("feasibility_assessment") or {}).get("research_ready"),
            "master_thesis_ready": ((state["brief"] or {}).get("feasibility_assessment") or {}).get("thesis_ready"),
            "contract_approval_status": (state["brief"] or {}).get("approval_status"),
            "contract_validation_errors": (state["brief"] or {}).get("validation_errors", []),
            "hypothesis_count": len(state["hypotheses"]),
            "claim_count": len(state["claims"]),
            "open_uncertainty_count": len([item for item in uncertainties if item["status"] == "open"]),
            "milestone_status": {item["milestone_key"]: item["status"] for item in state["milestones"]},
            "latest_decision": state["decisions"][-1] if state["decisions"] else None,
        }


research_state_service = ResearchStateService()
