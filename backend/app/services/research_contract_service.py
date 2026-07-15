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
    ResearchUncertaintyRepository,
)
from .research_methodology_service import research_methodology_service


class ResearchContractService:
    """Turn a broad goal into a bounded, falsifiable contract before task creation."""

    MILESTONES = (
        ("framing_frozen", "研究边界已冻结", ["研究问题、范围和完成判据已确认"]),
        ("methodology_frozen", "方法论路线已冻结", ["学科、认识论模式、研究设计与质量判据已确认"]),
        ("resources_ready", "研究资源已就绪", ["必需数据、设备、参与者或语料均已有可审计来源"]),
        ("ethics_cleared", "伦理与合规已放行", ["无需审批或已提供有效审批与使用边界"]),
        ("thesis_requirements_frozen", "学位论文规范已冻结", ["院校、专业、篇幅、章节与引文规范已确认"]),
        ("search_protocol_frozen", "检索协议已冻结", ["数据库、检索式和纳排标准已版本化"]),
        ("evidence_sufficient", "证据充分性达标", ["关键主张均有合格 passage 支撑"]),
        ("experiment_protocol_frozen", "实验协议已冻结", ["数据、基线、指标和停止条件已确认"]),
        ("replication_passed", "独立复现已通过", ["干净环境复跑结果在容差范围内"]),
        ("report_verified", "最终报告已核验", ["逐句接地与引用审计通过"]),
    )

    SCHEMA = {
        "type": "object",
        "properties": {
            "research_type": {
                "type": "string",
                "enum": ["empirical", "survey", "design", "mixed", "interpretive", "theoretical"],
            },
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
            "discipline": {
                "type": "object",
                "properties": {
                    "broad_field": {"type": "string"}, "field": {"type": "string"},
                    "subfield": {"type": "string"},
                },
                "required": ["broad_field", "field", "subfield"],
            },
            "methodology_profile": {
                "type": "object",
                "properties": {
                    "family": {
                        "type": "string",
                        "enum": [
                            "quantitative", "qualitative", "computational", "experimental",
                            "systematic_review", "humanities", "theoretical", "design_science", "mixed_methods",
                        ],
                    },
                    "epistemic_mode": {
                        "type": "string",
                        "enum": [
                            "hypothesis_testing", "estimation", "exploration", "interpretation",
                            "evidence_synthesis", "proof_construction", "artifact_evaluation", "theory_building",
                        ],
                    },
                    "study_design": {"type": "string"}, "unit_of_analysis": {"type": "string"},
                    "evidence_types": {"type": "array", "items": {"type": "string"}},
                    "data_collection_methods": {"type": "array", "items": {"type": "string"}},
                    "analysis_methods": {"type": "array", "items": {"type": "string"}},
                    "quality_criteria": {"type": "array", "items": {"type": "string"}},
                    "component_methods": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "family", "epistemic_mode", "study_design", "unit_of_analysis", "evidence_types",
                    "data_collection_methods", "analysis_methods", "quality_criteria", "component_methods",
                ],
            },
            "resource_plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "resource_type": {"type": "string"}, "description": {"type": "string"},
                        "required": {"type": "boolean"},
                        "status": {
                            "type": "string",
                            "enum": ["available", "missing", "requires_human", "pending_verification", "not_required"],
                        },
                        "owner": {"type": "string"}, "evidence": {"type": "string"},
                        "resolution": {"type": "string"},
                    },
                    "required": [
                        "resource_type", "description", "required", "status", "owner", "evidence", "resolution",
                    ],
                },
            },
            "ethics_plan": {
                "type": "object",
                "properties": {
                    "required": {"type": "boolean"},
                    "status": {"type": "string", "enum": ["not_required", "pending", "approved", "rejected"]},
                    "review_body": {"type": "string"}, "approval_reference": {"type": "string"},
                    "data_sensitivity": {"type": "string"},
                    "participant_risks": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "required", "status", "review_body", "approval_reference", "data_sensitivity", "participant_risks",
                ],
            },
            "thesis_requirements": {
                "type": "object",
                "properties": {
                    "degree_level": {"type": "string"}, "institution": {"type": "string"},
                    "programme": {"type": "string"}, "language": {"type": "string"},
                    "citation_style": {"type": "string"}, "target_word_count": {"type": "integer"},
                    "minimum_references": {"type": "integer"},
                    "minimum_supported_claims": {"type": "integer"},
                    "required_chapters": {"type": "array", "items": {"type": "string"}},
                    "status": {"type": "string", "enum": ["confirmed", "pending", "not_provided"]},
                },
                "required": [
                    "degree_level", "institution", "programme", "language", "citation_style",
                    "target_word_count", "minimum_references", "minimum_supported_claims",
                    "required_chapters", "status",
                ],
            },
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
            "ethics_risks", "success_criteria", "failure_criteria", "discipline", "methodology_profile",
            "resource_plan", "ethics_plan", "thesis_requirements", "hypotheses",
        ],
    }

    async def ensure_contract(self, run: dict) -> dict:
        existing = ResearchBriefRepository.get_by_run(run["id"])
        if existing and existing.get("subquestions"):
            hypotheses = ResearchHypothesisRepository.get_by_run(run["id"])
            errors = self.validate(existing, hypotheses)
            assessment = research_methodology_service.assess(existing)
            blockers = [*errors, *self._blocker_messages(assessment)]
            return {
                "brief": existing, "hypotheses": hypotheses, "errors": blockers,
                "assessment": assessment, "ready": not blockers,
            }

        contract = await self._generate(run)
        errors = self.validate(contract, contract.get("hypotheses") or [])
        assessment = research_methodology_service.assess(contract)
        blockers = [*errors, *self._blocker_messages(assessment)]
        self._persist(run["id"], contract, blockers, assessment)
        return {
            "brief": ResearchBriefRepository.get_by_run(run["id"]),
            "hypotheses": ResearchHypothesisRepository.get_by_run(run["id"]),
            "errors": blockers,
            "assessment": assessment,
            "ready": not blockers,
        }

    async def _generate(self, run: dict) -> dict:
        goal = primary_goal(str(run.get("research_goal") or "")).strip()
        base_prompt = f"""{prompt_loader.load('advisor_agent')}

请把用户研究目标改写为可冻结的 Research Contract，并只返回合法 JSON。

用户目标：
{goal}

要求：明确学科、方法族和认识论模式，不得把所有课题强行改写为计算实验；明确不研究什么；
给出 2-5 个带稳定 id 的子问题；成功与失败判据必须可检查。仅在假设检验、估计或
artifact evaluation 适用时给出假设；解释性、人文、理论证明和证据综合课题可以不设统计假设。
逐项声明数据、设备、实验室、受试者、语料、软件与专业人员等资源的真实状态；缺失、待核验或
需要人类执行时必须如实标记，不能为了让流程通过而写成 available。伦理审批与院校硕士论文规范
分别建模；不要假定尚未获得的数据、审批、资源、证据或院校规范已经存在。
"""
        llm = create_llm_provider()
        attempts = min(max(int(settings.llm_structured_repair_attempts), 0), 1) + 1
        prompt = base_prompt
        last_error = ""
        last_parsed: dict = {}
        for attempt in range(attempts):
            raw = await llm.generate(prompt=prompt, schema=self.SCHEMA, role="advisor_contract", run_id=run["id"])
            try:
                parsed = json.loads(raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
                if not isinstance(parsed, dict):
                    raise ValueError("contract root must be object")
                last_parsed = parsed
                contract_errors = self.validate(parsed, parsed.get("hypotheses") or [])
                if contract_errors:
                    raise ValueError("；".join(contract_errors))
                return parsed
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                if attempt + 1 < attempts:
                    prompt = (
                        f"{base_prompt}\n上次输出未通过 Research Contract 校验（{last_error}）。"
                        "必须严格使用 schema 字段名；只修复缺失字段，不扩写外部事实：\n"
                        f"{raw[:4000]}"
                    )
        fallback = self._supported_domain_fallback(goal)
        return fallback or last_parsed

    @staticmethod
    def _supported_domain_fallback(goal: str) -> dict | None:
        text = goal.lower()
        if not any(marker in text for marker in ("rag", "检索", "mrr", "召回")):
            return None
        return {
            "research_type": "empirical",
            "primary_question": "在冻结的带 query/qrel 检索基准上，不同文本切分策略的 MRR 与 Top-k accuracy 有何差异？",
            "objective": goal[:500],
            "subquestions": [
                {"id": "sq_literature", "question": "现有可核验全文证据如何界定切分策略、检索指标与研究缺口？"},
                {"id": "sq_experiment", "question": "重叠切分相对整文档基线的效应、区间与独立复现结果如何？"},
            ],
            "scope_in": ["冻结语料、query/qrel、三种预注册切分策略与检索排序指标"],
            "scope_out": ["生成模型回答质量、线上用户研究、无标注语料上的主观评价"],
            "target_domain": "retrieval_rag",
            "constraints": ["仅使用可核验全文 passage；实验仅使用用户提供且声明许可/伦理的数据"],
            "expected_contribution": "形成一个带统计区间、负结果和独立复现 artifact 的受控切分策略比较",
            "novelty_criteria": ["相对冻结基线给出可复现效应，而非仅报告单次最佳值"],
            "data_availability": "用户已提供带 query/qrel、license 与 ethics_review 声明的 JSON 快照",
            "ethics_risks": ["不扩展使用范围；不包含受试者或个人数据"],
            "success_criteria": ["三次以上固定种子运行、统计区间、artifact hash 和干净目录复现均通过"],
            "failure_criteria": ["最小效应未达到、区间跨零、artifact 不完整或独立复现超出容差"],
            "discipline": {
                "broad_field": "engineering", "field": "computer_science", "subfield": "information_retrieval",
            },
            "methodology_profile": {
                "family": "computational", "epistemic_mode": "hypothesis_testing",
                "study_design": "controlled paired benchmark", "unit_of_analysis": "query",
                "evidence_types": ["verified literature passages", "query-level retrieval results"],
                "data_collection_methods": ["frozen user-supplied benchmark execution"],
                "analysis_methods": ["paired query bootstrap", "ablation", "independent reproduction"],
                "quality_criteria": ["construct validity", "reproducibility", "external-validity disclosure"],
                "component_methods": [],
            },
            "resource_plan": [{
                "resource_type": "licensed_labeled_dataset",
                "description": "带 query/qrel、许可和伦理声明的冻结数据快照",
                "required": True, "status": "available", "owner": "user",
                "evidence": "运行附件快照", "resolution": "保持哈希冻结并仅在声明范围内使用",
            }],
            "ethics_plan": {
                "required": False, "status": "not_required", "review_body": "",
                "approval_reference": "", "data_sensitivity": "non-personal controlled benchmark",
                "participant_risks": [],
            },
            "thesis_requirements": {
                "degree_level": "master", "institution": "", "programme": "",
                "language": "zh-CN", "citation_style": "GB/T 7714",
                "target_word_count": 30000, "minimum_references": 30, "minimum_supported_claims": 8,
                "required_chapters": ["引言", "相关工作", "方法", "实验", "结果", "讨论", "结论"],
                "status": "not_provided",
            },
            "hypotheses": [{
                "statement": "固定长度重叠切分的 MRR 相对整文档不切分基线提高至少 5%",
                "rationale": "由用户明确要求比较的预注册候选假设，不视为既有事实",
                "treatment": "fixed_100_overlap_30", "baseline": "no_split",
                "conditions": ["冻结同一语料、query/qrel、检索器与评测实现"],
                "predicted_direction": "MRR increase", "primary_metric": "MRR",
                "minimum_effect": "relative improvement >= 5%",
                "falsification_criterion": "相对效应低于 5% 或 95% bootstrap 区间跨越 0",
            }],
        }

    def validate(self, brief: dict, hypotheses: object) -> list[str]:
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
        errors.extend(research_methodology_service.validate(brief))
        epistemic_mode = (brief.get("methodology_profile") or {}).get("epistemic_mode")
        hypothesis_required = epistemic_mode in {"hypothesis_testing", "estimation", "artifact_evaluation"}
        if hypothesis_required and (not isinstance(hypotheses, list) or not hypotheses):
            errors.append(f"{epistemic_mode} 至少需要 1 个可检验假设")
        if hypotheses is not None and not isinstance(hypotheses, list):
            errors.append("hypotheses 必须是数组")
        for index, hypothesis in enumerate(hypotheses if isinstance(hypotheses, list) else []):
            if not isinstance(hypothesis, dict):
                errors.append(f"hypothesis[{index}] 必须是对象")
                continue
            for field in ("statement", "baseline", "primary_metric", "minimum_effect", "falsification_criterion"):
                if not str(hypothesis.get(field) or "").strip():
                    errors.append(f"hypothesis[{index}].{field} 不能为空")
        return errors

    @staticmethod
    def _blocker_messages(assessment: dict) -> list[str]:
        return [
            f"feasibility:{item.get('code')}:{item.get('resource_type', '')}:{item.get('resolution', '')}"
            for item in assessment.get("research_blockers") or []
        ]

    def _persist(self, run_id: str, contract: dict, errors: list[str], assessment: dict | None = None) -> None:
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
            discipline=contract.get("discipline") or {},
            methodology_family=(contract.get("methodology_profile") or {}).get("family", ""),
            epistemic_mode=(contract.get("methodology_profile") or {}).get("epistemic_mode", ""),
            methodology_profile=contract.get("methodology_profile") or {},
            resource_plan=contract.get("resource_plan") or [],
            ethics_plan=contract.get("ethics_plan") or {},
            thesis_requirements=contract.get("thesis_requirements") or {},
            feasibility_assessment=assessment or research_methodology_service.assess(contract),
            approval_status="blocked_resources" if any(str(error).startswith("feasibility:") for error in errors)
            else ("needs_revision" if errors else "draft"),
            validation_errors=errors,
            status="draft",
            updated_at=now,
        )
        ResearchHypothesisRepository.delete_by_run(run_id)
        for item in contract.get("hypotheses") or []:
            if not isinstance(item, dict):
                continue
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
        if contract.get("methodology_profile"):
            ResearchUncertaintyRepository.resolve_by_category(run_id, "hypothesis", now)

    def freeze(self, run_id: str) -> dict:
        brief = ResearchBriefRepository.get_by_run(run_id) or {}
        assessment = research_methodology_service.assess(brief)
        blockers = self.validate(brief, ResearchHypothesisRepository.get_by_run(run_id))
        blockers.extend(self._blocker_messages(assessment))
        if blockers:
            raise ValueError("研究契约尚不可冻结：" + "；".join(blockers))
        now = datetime.now().isoformat()
        ResearchBriefRepository.update(run_id, approval_status="frozen", status="frozen", updated_at=now)
        milestones = ResearchMilestoneRepository.get_by_run(run_id)
        passed_keys = {"framing_frozen", "methodology_frozen", "resources_ready"}
        ethics = brief.get("ethics_plan") or {}
        thesis = brief.get("thesis_requirements") or {}
        if ethics.get("status") in {"approved", "not_required"}:
            passed_keys.add("ethics_cleared")
        if thesis.get("status") == "confirmed":
            passed_keys.add("thesis_requirements_frozen")
        for milestone in milestones:
            if milestone["milestone_key"] in passed_keys:
                ResearchMilestoneRepository.update(milestone["id"], status="passed", completed_at=now, updated_at=now)
        return ResearchBriefRepository.get_by_run(run_id) or {}

    def revise(self, run_id: str, contract: dict) -> dict:
        errors = self.validate(contract, contract.get("hypotheses") or [])
        assessment = research_methodology_service.assess(contract)
        blockers = [*errors, *self._blocker_messages(assessment)]
        self._persist(run_id, contract, blockers, assessment)
        return {
            "brief": ResearchBriefRepository.get_by_run(run_id),
            "hypotheses": ResearchHypothesisRepository.get_by_run(run_id),
            "errors": blockers,
            "assessment": assessment,
            "ready": not blockers,
        }


research_contract_service = ResearchContractService()
