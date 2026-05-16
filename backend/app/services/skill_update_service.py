from __future__ import annotations


class SkillUpdateService:
    def update_after_review(self, agent_id: str, task_id: str, review_score: float):
        return self.get_suggested_updates(agent_id, review_score=review_score, task_id=task_id)

    def get_suggested_updates(self, agent_id: str, review_score: float | None = None, task_id: str | None = None) -> dict:
        recommendation = "保持"
        if review_score is not None and review_score >= 0.9:
            recommendation = "建议提升相关技能置信度"
        elif review_score is not None and review_score < 0.6:
            recommendation = "建议复盘并降低相关技能置信度"
        return {
            "status": "advisory_only",
            "agent_id": agent_id,
            "task_id": task_id,
            "recommendation": recommendation,
            "auto_apply": False,
        }


skill_update_service = SkillUpdateService()
