import json

from ..core.config import settings
from ..core.logger import logger
from ..models.agent_skill import AgentSkillCreate
from ..storage.repositories import AgentSkillRepository
from .agent_skill_service import agent_skill_service
from .run_event_service import run_event_service
from .skill_evaluator import skill_evaluator


class SkillReflectionService:
    def capture_after_review(self, task: dict, review: dict) -> list[dict]:
        if not settings.agent_skill_enabled or not settings.skill_auto_capture_enabled:
            return []
        if not review.get("approved"):
            return []
        if not task.get("owner_agent") or not task.get("outputs"):
            return []

        created: list[dict] = []
        owner_candidate = self._build_task_candidate(task, review)
        owner_result = self._maybe_create(owner_candidate, task)
        if owner_result:
            created.append(owner_result)

        advisor_candidate = self._build_advisor_candidate(task, review)
        advisor_result = self._maybe_create(advisor_candidate, task) if advisor_candidate else None
        if advisor_result:
            created.append(advisor_result)
        return created

    def _maybe_create(self, candidate: dict, task: dict) -> dict | None:
        if self._already_captured(candidate["agent_id"], task["id"], candidate["title"]):
            return None
        evaluation = skill_evaluator.evaluate(candidate)
        run_id = task.get("run_id")
        if not evaluation["accepted"]:
            if run_id:
                run_event_service.emit(
                    run_id,
                    "skill.rejected",
                    "skill",
                    "Skill 候选未沉淀",
                    evaluation["reason"],
                    task_id=task["id"],
                    agent_id=candidate["agent_id"],
                    payload={"title": candidate["title"], "evaluation": evaluation},
                )
            return None

        status = settings.skill_default_status if settings.skill_default_status in {"draft", "active", "disabled"} else "draft"
        skill = agent_skill_service.create(
            AgentSkillCreate(
                agent_id=candidate["agent_id"],
                title=candidate["title"],
                description=candidate["description"],
                content=candidate["content"],
                status=status,
                confidence=evaluation["confidence"],
                source_run_id=run_id,
                source_task_id=task["id"],
                tags=candidate["tags"],
            )
        )
        if run_id:
            run_event_service.emit(
                run_id,
                "skill.created",
                "skill",
                "Skill 已沉淀",
                f"{candidate['agent_id']} 新增 skill：{candidate['title']}",
                task_id=task["id"],
                agent_id=candidate["agent_id"],
                payload={"skill_id": skill["id"], "evaluation": evaluation},
            )
        logger.info("[SkillReflection] skill created | task_id=%s | agent_id=%s | skill_id=%s", task["id"], candidate["agent_id"], skill["id"])
        return skill

    def _already_captured(self, agent_id: str, task_id: str, title: str) -> bool:
        for skill in AgentSkillRepository.get_all(agent_id=agent_id):
            if skill.get("source_task_id") == task_id and skill.get("title") == title:
                return True
        return False

    def _build_task_candidate(self, task: dict, review: dict) -> dict:
        task_type = task.get("task_type", "")
        outputs = task.get("outputs", [])
        output_summary = self._summarize_outputs(outputs)
        title = f"{task.get('title', '任务')} 的可复用执行经验"
        content = "\n".join(
            [
                "## 适用场景",
                "",
                f"- 当 {task.get('owner_agent')} 处理同类 `{task_type}` 任务，并需要复用本次任务的执行流程、风险判断或输出结构时。",
                "",
                "## 触发条件",
                "",
                f"- 任务类型为 `{task_type}`。",
                "- 需要产出结构化调研、分析、实验或写作结果。",
                "- 需要避免重复踩到本次任务暴露的问题。",
                "",
                "## 操作步骤",
                "",
                "- 先复述任务目标和约束，确认输出格式。",
                "- 对任务产出中的关键发现、风险和下一步进行结构化整理。",
                "- 在提交前用导师审核反馈检查是否缺少证据、边界或可复现信息。",
                "",
                "## 本次可复用要点",
                "",
                output_summary,
                "",
                "## 反例",
                "",
                "- 如果只是一次性事实、具体项目名称或不可复用结论，不应套用本 skill。",
                "- 如果用户提供了敏感材料，不要把原文或密钥沉淀到长期 skill。",
                "",
                "## 来源摘要",
                "",
                f"- 来源任务：{task.get('title', '')}",
                f"- 导师审核：{review.get('feedback', '')[:500]}",
            ]
        )
        return {
            "agent_id": task["owner_agent"],
            "title": title,
            "description": f"从任务 {task.get('title', '')} 中沉淀的可复用经验。",
            "content": content,
            "tags": [task_type, "auto-captured"],
        }

    def _build_advisor_candidate(self, task: dict, review: dict) -> dict | None:
        feedback = str(review.get("feedback", "")).strip()
        if len(feedback) < 120:
            return None
        content = "\n".join(
            [
                "## 适用场景",
                "",
                "- 当导师 Agent 审核同类任务时，用于检查任务是否具备结论、依据、边界和下一步。",
                "",
                "## 触发条件",
                "",
                f"- 任务类型为 `{task.get('task_type', '')}`。",
                "- 审核反馈包含可复用的质量标准或常见问题。",
                "",
                "## 操作步骤",
                "",
                "- 对照任务目标检查产出是否完整。",
                "- 明确指出缺失证据、结论跳跃、风险遗漏或格式不合规。",
                "- 给出可执行的修改建议。",
                "",
                "## 本次审核准则",
                "",
                f"- {feedback}",
                "",
                "## 反例",
                "",
                "- 只包含一次性项目事实或用户隐私的反馈，不应复用。",
            ]
        )
        return {
            "agent_id": "advisor",
            "title": f"{task.get('task_type', '任务')} 审核准则沉淀",
            "description": "从导师审核反馈中沉淀的质量检查规则。",
            "content": content,
            "tags": [task.get("task_type", ""), "advisor-review", "auto-captured"],
        }

    def _summarize_outputs(self, outputs: list) -> str:
        points: list[str] = []
        for output in outputs:
            if isinstance(output, dict):
                for key in ("summary", "conclusion", "final_conclusion", "recommendations", "next_steps", "risks"):
                    value = output.get(key)
                    if value:
                        points.append(f"- {key}: {json.dumps(value, ensure_ascii=False)[:500]}")
                for key in ("findings", "deliverables", "metrics", "key_metrics", "procedure", "sections"):
                    value = output.get(key)
                    if value:
                        points.append(f"- {key}: {json.dumps(value, ensure_ascii=False)[:500]}")
        return "\n".join(points[:8]) if points else "- 本次输出没有足够结构化要点，后续任务使用前需要人工补充。"


skill_reflection_service = SkillReflectionService()
