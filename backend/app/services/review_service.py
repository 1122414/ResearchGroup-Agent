import json
import uuid
from datetime import datetime

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.logger import logger
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import OutputRepository, ReviewDecisionRepository, TaskRepository


class ReviewService:
    async def review(self, task: dict) -> dict:
        logger.info("[ReviewService] review started | task_id=%s | title=%s", task.get("id"), task.get("title", "")[:40])
        latest = self._latest_output(task)
        if task.get("task_type") == "literature_survey" and (
            latest.get("insufficient_evidence") or latest.get("integrity_blocked")
        ):
            return self._review_insufficient_evidence(task, latest)
        system_prompt = prompt_loader.load("advisor_agent")
        user_prompt = f"""请作为导师 Agent 审核以下任务产出。
任务标题：{task.get('title', '')}
任务类型：{task.get('task_type', '')}
任务描述：{task.get('description', '')}
任务输出：{json.dumps(task.get('outputs', []), ensure_ascii=False, indent=2)}

请返回 JSON：{{"approved": true/false, "feedback": "审核意见"}}"""

        llm = create_llm_provider()
        logger.info("[ReviewService] calling LLM | task_id=%s | role=advisor_review", task.get("id"))
        raw_response = await llm.generate(
            prompt=f"{system_prompt}\n\n---\n\n{user_prompt}",
            schema={
                "type": "object",
                "properties": {
                    "approved": {"type": "boolean"},
                    "feedback": {"type": "string"},
                },
                "required": ["approved", "feedback"],
            },
            role="advisor_review",
            run_id=task.get("run_id"),
            task_id=task["id"],
            agent_id=task.get("owner_agent"),
        )

        llm_review = self._parse_review(raw_response)
        rubric = self._rubric_for_task(task.get("task_type", ""))
        scores = self._score_task(task, llm_review, rubric)
        average_score = round(sum(scores.values()) / max(len(scores), 1), 4)
        approved = bool(llm_review.get("approved", False)) and average_score >= rubric["threshold"]
        review = {
            **llm_review,
            "approved": approved,
            "rubric": rubric,
            "scores": scores,
            "average_score": average_score,
            "requires_revision": not approved,
        }
        logger.info(
            "[ReviewService] review result | task_id=%s | approved=%s | score=%.4f",
            task.get("id"),
            approved,
            average_score,
        )
        self._persist_review(task, review)
        return review

    def _review_insufficient_evidence(self, task: dict, latest: dict) -> dict:
        rubric = self._rubric_for_task(task.get("task_type", ""))
        feedback = (
            "系统未检索到足够的可核验来源，当前输出已按学术诚信策略标记为证据不足。"
            "请先扩大或修复检索链路，再继续文献综述；不得基于模型记忆、常识或不可核验来源补写参考文献。"
        )
        scores = self._score_task(task, {"approved": False}, rubric)
        average_score = round(sum(scores.values()) / max(len(scores), 1), 4)
        review = {
            "approved": False,
            "feedback": feedback,
            "rubric": rubric,
            "scores": scores,
            "average_score": average_score,
            "requires_revision": True,
            "review_mode": "insufficient_evidence_guardrail",
            "source_mode": latest.get("source_mode"),
        }
        logger.info(
            "[ReviewService] insufficient evidence guardrail | task_id=%s | score=%.4f",
            task.get("id"),
            average_score,
        )
        self._persist_review(task, review)
        return review

    def _persist_review(self, task: dict, review: dict) -> None:
        ReviewDecisionRepository.insert(
            {
                "id": f"review_decision_{uuid.uuid4().hex[:10]}",
                "run_id": task.get("run_id"),
                "task_id": task["id"],
                "rubric": review["rubric"],
                "scores": review["scores"],
                "approved": review["approved"],
                "feedback": review.get("feedback", ""),
                "requires_revision": review["requires_revision"],
                "created_at": datetime.now().isoformat(),
            }
        )
        TaskRepository.update_status(
            task["id"],
            "completed" if review["approved"] else "need_revision",
            review_result=review,
            review_feedback=review.get("feedback", ""),
        )
        if review["approved"] and task.get("revision_of_task_id"):
            parent = TaskRepository.get_by_id(task["revision_of_task_id"])
            if parent:
                TaskRepository.update_status(
                    parent["id"],
                    "completed",
                    blocked_reason=None,
                    review_result=review,
                    review_feedback=f"返工任务 {task['id']} 已通过审核。",
                )
        OutputRepository.insert(
            {
                "id": f"review_{task['id']}",
                "output_type": "review",
                "title": f"导师审核：{task.get('title', '')}",
                "content": json.dumps(review, ensure_ascii=False, indent=2),
                "run_id": task.get("run_id"),
                "task_id": task["id"],
                "agent_id": task.get("owner_agent"),
                "created_at": datetime.now().isoformat(),
            }
        )

    @staticmethod
    def _latest_output(task: dict) -> dict:
        outputs = task.get("outputs", []) or []
        return outputs[-1] if outputs and isinstance(outputs[-1], dict) else {}

    def _parse_review(self, raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        try:
            parsed = json.loads(text.strip())
            if isinstance(parsed, dict) and isinstance(parsed.get("approved"), bool):
                return {"approved": parsed["approved"], "feedback": str(parsed.get("feedback") or "")}
        except json.JSONDecodeError:
            pass
        return {"approved": False, "feedback": "导师审核返回缺失或非法结构，已按不通过处理；请人工检查或有限重试。"}

    def _rubric_for_task(self, task_type: str) -> dict:
        dimensions = {
            "literature_survey": {"coverage": 0.25, "traceability": 0.35, "method_mapping": 0.25, "clarity": 0.15},
            "system_design": {"feasibility": 0.35, "interfaces": 0.25, "risk_control": 0.2, "clarity": 0.2},
            "experiment_design": {"reproducibility": 0.35, "baseline": 0.2, "metrics": 0.25, "safety": 0.2},
            "result_analysis": {"completeness": 0.3, "interpretation": 0.3, "evidence": 0.2, "clarity": 0.2},
            "report_writing": {"structure": 0.25, "evidence": 0.3, "completeness": 0.25, "clarity": 0.2},
        }.get(task_type, {"quality": 1.0})
        return {"dimensions": dimensions, "threshold": settings.review_pass_threshold}

    def _score_task(self, task: dict, review: dict, rubric: dict) -> dict[str, float]:
        outputs = task.get("outputs", []) or []
        latest = outputs[-1] if outputs and isinstance(outputs[-1], dict) else {}
        scores: dict[str, float] = {}
        for dimension in rubric["dimensions"]:
            score = settings.review_default_approved_score if review.get("approved", True) else settings.review_default_rejected_score
            if dimension == "traceability":
                score = 1.0 if latest.get("papers_read") or latest.get("insufficient_evidence") else settings.review_traceability_missing_score
            elif dimension == "method_mapping":
                score = 1.0 if latest.get("methods_found") or latest.get("insufficient_evidence") else settings.review_missing_score
            elif dimension == "reproducibility":
                score = 1.0 if latest.get("reproducible_experiment", {}).get("experiment_ran") else 0.4
            elif dimension == "baseline":
                metrics = latest.get("reproducible_experiment", {}).get("metrics", {})
                score = 1.0 if metrics.get("rows") else settings.review_missing_score
            elif dimension == "metrics":
                score = 1.0 if latest.get("reproducible_experiment", {}).get("metrics") else settings.review_missing_score
            elif dimension == "evidence":
                if task.get("task_type") == "report_writing":
                    score = settings.review_report_evidence_score if latest else settings.review_default_rejected_score
                elif task.get("task_type") == "result_analysis":
                    score = 1.0 if latest.get("key_metrics") or latest.get("metrics") else settings.review_default_rejected_score
                else:
                    score = 1.0 if latest.get("papers_read") or latest.get("reproducible_experiment") else settings.review_default_rejected_score
            scores[dimension] = round(score, 4)
        return scores


review_service = ReviewService()
