from __future__ import annotations


class ResearchMethodologyService:
    """Validate a discipline-neutral methodology and expose honest feasibility gates."""

    FAMILIES = {
        "quantitative", "qualitative", "computational", "experimental",
        "systematic_review", "humanities", "theoretical", "design_science", "mixed_methods",
    }
    EPISTEMIC_MODES = {
        "hypothesis_testing", "estimation", "exploration", "interpretation",
        "evidence_synthesis", "proof_construction", "artifact_evaluation", "theory_building",
    }
    RESOURCE_STATUSES = {"available", "missing", "requires_human", "pending_verification", "not_required"}
    ETHICS_STATUSES = {"not_required", "pending", "approved", "rejected"}
    THESIS_STATUSES = {"confirmed", "pending", "not_provided"}

    def validate(self, contract: dict) -> list[str]:
        errors: list[str] = []
        discipline = contract.get("discipline") or {}
        profile = contract.get("methodology_profile") or {}
        resources = contract.get("resource_plan")
        ethics = contract.get("ethics_plan") or {}
        thesis = contract.get("thesis_requirements") or {}

        if not all(str(discipline.get(key) or "").strip() for key in ("broad_field", "field")):
            errors.append("discipline.broad_field 与 discipline.field 不能为空")
        if profile.get("family") not in self.FAMILIES:
            errors.append("methodology_profile.family 不受支持")
        if profile.get("epistemic_mode") not in self.EPISTEMIC_MODES:
            errors.append("methodology_profile.epistemic_mode 不受支持")
        for field in ("study_design", "unit_of_analysis"):
            if not str(profile.get(field) or "").strip():
                errors.append(f"methodology_profile.{field} 不能为空")
        for field in ("evidence_types", "analysis_methods", "quality_criteria"):
            if not isinstance(profile.get(field), list) or not profile.get(field):
                errors.append(f"methodology_profile.{field} 不能为空")
        if len(profile.get("quality_criteria") or []) < 2:
            errors.append("methodology_profile.quality_criteria 至少需要 2 项")
        if profile.get("family") == "mixed_methods" and len(profile.get("component_methods") or []) < 2:
            errors.append("mixed_methods 至少需要 2 个 component_methods")

        if not isinstance(resources, list) or not resources:
            errors.append("resource_plan 不能为空")
        for index, resource in enumerate(resources if isinstance(resources, list) else []):
            if not isinstance(resource, dict):
                errors.append(f"resource_plan[{index}] 必须是对象")
                continue
            if not str(resource.get("resource_type") or "").strip():
                errors.append(f"resource_plan[{index}].resource_type 不能为空")
            if resource.get("status") not in self.RESOURCE_STATUSES:
                errors.append(f"resource_plan[{index}].status 不合法")
            if not isinstance(resource.get("required"), bool):
                errors.append(f"resource_plan[{index}].required 必须是布尔值")

        if not isinstance(ethics.get("required"), bool):
            errors.append("ethics_plan.required 必须是布尔值")
        if ethics.get("status") not in self.ETHICS_STATUSES:
            errors.append("ethics_plan.status 不合法")
        if ethics.get("required") and ethics.get("status") == "not_required":
            errors.append("需要伦理审查时 ethics_plan.status 不能为 not_required")
        if not ethics.get("required") and ethics.get("status") not in {"not_required", "approved"}:
            errors.append("无需伦理审查时 ethics_plan.status 应为 not_required 或 approved")

        if str(thesis.get("degree_level") or "").lower() not in {"master", "硕士"}:
            errors.append("thesis_requirements.degree_level 必须为 master/硕士")
        if thesis.get("status") not in self.THESIS_STATUSES:
            errors.append("thesis_requirements.status 不合法")
        for field in ("language", "citation_style"):
            if not str(thesis.get(field) or "").strip():
                errors.append(f"thesis_requirements.{field} 不能为空")
        if not isinstance(thesis.get("required_chapters"), list) or not thesis.get("required_chapters"):
            errors.append("thesis_requirements.required_chapters 不能为空")
        try:
            if int(thesis.get("target_word_count") or 0) < 1000:
                errors.append("thesis_requirements.target_word_count 必须至少为 1000")
        except (TypeError, ValueError):
            errors.append("thesis_requirements.target_word_count 必须是整数")
        return errors

    def assess(self, contract: dict) -> dict:
        resources = contract.get("resource_plan") or []
        ethics = contract.get("ethics_plan") or {}
        thesis = contract.get("thesis_requirements") or {}
        research_blockers: list[dict] = []
        thesis_blockers: list[dict] = []

        for resource in resources:
            if not isinstance(resource, dict) or not resource.get("required"):
                continue
            status = resource.get("status")
            if status in {"missing", "requires_human", "pending_verification"}:
                research_blockers.append({
                    "code": f"resource_{status}",
                    "resource_type": resource.get("resource_type", "unknown"),
                    "description": resource.get("description", ""),
                    "owner": resource.get("owner", "user_or_institution"),
                    "resolution": resource.get("resolution", "提供可审计的资源或完成记录"),
                })

        if ethics.get("required") and ethics.get("status") != "approved":
            research_blockers.append({
                "code": "ethics_approval_required",
                "resource_type": "ethics_approval",
                "description": "涉及人类参与者、敏感数据、动物或受监管材料的研究不得在审批前执行",
                "owner": ethics.get("review_body") or "user_or_institution",
                "resolution": "提供伦理审批编号与允许的数据/实验范围",
            })
        if thesis.get("status") != "confirmed":
            thesis_blockers.append({
                "code": "institutional_thesis_requirements_unconfirmed",
                "description": "院校格式、字数、章节、引文规范或提交要求尚未确认",
                "resolution": "提供并冻结目标院校/专业的学位论文规范",
            })
        thesis_blockers.extend(research_blockers)

        human_required = any(item.get("status") == "requires_human" for item in resources) or (
            ethics.get("required") and ethics.get("status") != "approved"
        )
        execution_mode = "human_led" if human_required else ("hybrid" if research_blockers else "autonomous")
        return {
            "research_ready": not research_blockers,
            "thesis_ready": not thesis_blockers,
            "execution_mode": execution_mode,
            "research_blockers": research_blockers,
            "thesis_blockers": thesis_blockers,
            "claim_policy": (
                "只有 research_ready 才能进入执行；只有 thesis_ready 且全部方法、证据、分析与论文门禁通过，"
                "才可标记为完整硕士论文。"
            ),
        }


research_methodology_service = ResearchMethodologyService()
