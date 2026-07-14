from __future__ import annotations

import json
import uuid
from datetime import datetime

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.prompt_loader import prompt_loader
from ..core.research_goal import primary_goal
from ..storage.repositories import (
    ResearchBriefRepository,
    ResearchHypothesisRepository,
    ResearchMilestoneRepository,
)


class ResearchContractService:
    """Turn a broad goal into a bounded, falsifiable contract before task creation."""

    MILESTONES = (
        ("framing_frozen", "研究边界已冻结", ["研究问题、范围和完成判据已确认"]),
        ("search_protocol_frozen", "检索协议已冻结", ["数据库、检索式和纳排标准已版本化"]),
        ("evidence_sufficient", "证据充分性达标", ["关键主张均有合格 passage 支撑"]),
        ("experiment_protocol_frozen", "实验协议已冻结", ["数据、基线、指标和停止条件已确认"]),
        ("replication_passed", "独立复现已通过", ["干净环境复跑结果在容差范围内"]),
        ("report_verified", "最终报告已核验", ["逐句接地与引用审计通过"]),
    )

    SCHEMA = {
        "type": "object",
        "properties": {
            "research_type": {"type": "string", "enum": ["empirical", "survey", "design", "mixed"]},
            "primary_question": {"type": "string"},
            "objective": {"type": "string"},
            "subquestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "question": {"type": "string"}},
                    "required": ["id", "question"],
                },
            },
            "scope_in": {"type": "array", "items": {"type": "string"}},
            "scope_out": {"type": "array", "items": {"type": "string"}},
            "target_domain": {"type": "string"},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "expected_contribution": {"type": "string"},
            "novelty_criteria": {"type": "array", "items": {"type": "string"}},
            "data_availability": {"type": "string"},
            "ethics_risks": {"type": "array", "items": {"type": "string"}},
            "success_criteria": {"type": "array", "items": {"type": "string"}},
            "failure_criteria": {"type": "array", "items": {"type": "string"}},
            "hypotheses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "string"}, "rationale": {"type": "string"},
                        "treatment": {"type": "string"}, "baseline": {"type": "string"},
                        "conditions": {"type": "array", "items": {"type": "string"}},
                        "predicted_direction": {"type": "string"}, "primary_metric": {"type": "string"},
                        "minimum_effect": {"type": "string"}, "falsification_criterion": {"type": "string"},
                    },
                    "required": [
                        "statement", "rationale", "treatment", "baseline", "conditions",
                        "predicted_direction", "primary_metric", "minimum_effect", "falsification_criterion",
                    ],
                },
            },
        },
        "required": [
            "research_type", "primary_question", "objective", "subquestions", "scope_in", "scope_out",
            "target_domain", "constraints", "expected_contribution", "novelty_criteria", "data_availability",
            "ethics_risks", "success_criteria", "failure_criteria", "hypotheses",
        ],
    }

    async def ensure_contract(self, run: dict) -> dict:
        existing = ResearchBriefRepository.get_by_run(run["id"])
        if existing and existing.get("subquestions"):
            errors = self.validate(existing, ResearchHypothesisRepository.get_by_run(run["id"]))
            return {"brief": existing, "hypotheses": ResearchHypothesisRepository.get_by_run(run["id"]), "errors": errors, "ready": not errors}

        contract = await self._generate(run)
        errors = self.validate(contract, contract.get("hypotheses") or [])
        self._persist(run["id"], contract, errors)
        return {
            "brief": ResearchBriefRepository.get_by_run(run["id"]),
            "hypotheses": ResearchHypothesisRepository.get_by_run(run["id"]),
            "errors": errors,
            "ready": not errors,
        }

    async def _generate(self, run: dict) -> dict:
        goal = primary_goal(str(run.get("research_goal") or "")).strip()
        base_prompt = f"""{prompt_loader.load('advisor_agent')}

请把用户研究目标改写为可冻结的 Research Contract，并只返回合法 JSON。

用户目标：
{goal}

要求：明确不研究什么；给出 2-5 个带稳定 id 的子问题；成功与失败判据必须可检查；
每个假设都必须包含基线、主指标、最小效应和可直接判伪的条件。不要假定尚未获得的数据或证据已经存在。
"""
        llm = create_llm_provider()
        attempts = min(max(int(settings.llm_structured_repair_attempts), 0), 1) + 1
        prompt = base_prompt
        last_error = ""
        for attempt in range(attempts):
            raw = await llm.generate(prompt=prompt, schema=self.SCHEMA, role="advisor_contract", run_id=run["id"])
            try:
                parsed = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
                if not isinstance(parsed, dict):
                    raise ValueError("contract root must be object")
                return parsed
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                if attempt + 1 < attempts:
                    prompt = f"{base_prompt}\n上次输出结构非法（{last_error}），只修复结构，不扩写事实：\n{raw[:4000]}"
        raise ValueError(f"Research Contract 结构化失败（{attempts} 次尝试）：{last_error}")

    def validate(self, brief: dict, hypotheses: list[dict]) -> list[str]:
        errors: list[str] = []
        question = str(brief.get("primary_question") or brief.get("research_question") or "").strip()
        if len(question) < 10:
            errors.append("primary_question 过于宽泛或为空")
        for field in ("subquestions", "scope_in", "scope_out", "success_criteria", "failure_criteria", "novelty_criteria"):
            if not brief.get(field):
                errors.append(f"{field} 不能为空")
        if len(brief.get("subquestions") or []) < 2:
            errors.append("至少需要 2 个子问题")
        for field in ("target_domain", "expected_contribution", "data_availability"):
            if not str(brief.get(field) or "").strip():
                errors.append(f"{field} 不能为空")
        if not hypotheses:
            errors.append("至少需要 1 个可证伪假设")
        for index, hypothesis in enumerate(hypotheses):
            for field in ("statement", "baseline", "primary_metric", "minimum_effect", "falsification_criterion"):
                if not str(hypothesis.get(field) or "").strip():
                    errors.append(f"hypothesis[{index}].{field} 不能为空")
        return errors

    def _persist(self, run_id: str, contract: dict, errors: list[str]) -> None:
        now = datetime.now().isoformat()
        ResearchBriefRepository.update(
            run_id,
            research_question=contract.get("primary_question", ""),
            objective=contract.get("objective", ""),
            scope="；".join(contract.get("scope_in") or []),
            research_type=contract.get("research_type", "empirical"),
            subquestions=contract.get("subquestions") or [],
            scope_in=contract.get("scope_in") or [],
            scope_out=contract.get("scope_out") or [],
            target_domain=contract.get("target_domain", ""),
            constraints=contract.get("constraints") or [],
            expected_contribution=contract.get("expected_contribution", ""),
            novelty_criteria=contract.get("novelty_criteria") or [],
            data_availability=contract.get("data_availability", ""),
            ethics_risks=contract.get("ethics_risks") or [],
            success_criteria=contract.get("success_criteria") or [],
            failure_criteria=contract.get("failure_criteria") or [],
            approval_status="needs_revision" if errors else "draft",
            validation_errors=errors,
            status="draft",
            updated_at=now,
        )
        ResearchHypothesisRepository.delete_by_run(run_id)
        for item in contract.get("hypotheses") or []:
            ResearchHypothesisRepository.insert(
                {
                    "id": f"hypothesis_{uuid.uuid4().hex[:10]}", "run_id": run_id,
                    "statement": item.get("statement", ""), "rationale": item.get("rationale", ""),
                    "status": "proposed", "confidence": 0.0,
                    "treatment": item.get("treatment", ""), "baseline": item.get("baseline", ""),
                    "conditions": item.get("conditions") or [], "predicted_direction": item.get("predicted_direction", ""),
                    "primary_metric": item.get("primary_metric", ""), "minimum_effect": item.get("minimum_effect", ""),
                    "falsification_criterion": item.get("falsification_criterion", ""),
                    "originating_evidence_ids": [], "competing_hypothesis_ids": [],
                    "created_at": now, "updated_at": now,
                }
            )
        milestones = [
            {
                "id": f"milestone_{uuid.uuid4().hex[:10]}", "milestone_key": key, "title": title,
                "status": "pending", "criteria": criteria, "evidence_ids": [],
                "completed_at": None, "created_at": now, "updated_at": now,
            }
            for key, title, criteria in self.MILESTONES
        ]
        ResearchMilestoneRepository.replace_for_run(run_id, milestones)

    def freeze(self, run_id: str) -> dict:
        now = datetime.now().isoformat()
        ResearchBriefRepository.update(run_id, approval_status="frozen", status="frozen", updated_at=now)
        milestones = ResearchMilestoneRepository.get_by_run(run_id)
        framing = next((item for item in milestones if item["milestone_key"] == "framing_frozen"), None)
        if framing:
            ResearchMilestoneRepository.update(framing["id"], status="passed", completed_at=now, updated_at=now)
        return ResearchBriefRepository.get_by_run(run_id) or {}

    def revise(self, run_id: str, contract: dict) -> dict:
        errors = self.validate(contract, contract.get("hypotheses") or [])
        self._persist(run_id, contract, errors)
        return {
            "brief": ResearchBriefRepository.get_by_run(run_id),
            "hypotheses": ResearchHypothesisRepository.get_by_run(run_id),
            "errors": errors,
            "ready": not errors,
        }


research_contract_service = ResearchContractService()
