"""
预留接口：SkillUpdateService
预留后续能力分数动态调整机制。
根据导师审核反馈自动调整 Agent 能力画像。
MVP 阶段仅保留空实现，不启用。
"""


class SkillUpdateService:
    def update_after_review(self, agent_id: str, task_id: str, review_score: float):
        pass

    def get_suggested_updates(self, agent_id: str) -> dict:
        return {"status": "not_implemented", "message": "MVP 阶段使用固定能力矩阵"}


skill_update_service = SkillUpdateService()
