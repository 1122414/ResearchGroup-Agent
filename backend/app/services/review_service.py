import json
from datetime import datetime

from ..core.llm_provider import create_llm_provider
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import OutputRepository, TaskRepository


class ReviewService:
    async def review(self, task: dict) -> dict:
        system_prompt = prompt_loader.load("advisor_agent")
        user_prompt = f"""请以导师 Agent 身份审核下面的任务产出。

任务标题：{task.get('title', '')}
任务类型：{task.get('task_type', '')}
任务说明：{task.get('description', '')}
任务产出：
{json.dumps(task.get('outputs', []), ensure_ascii=False, indent=2)}

请返回 JSON：{{"approved": true/false, "feedback": "审核意见"}}。
"""

        raw_response = await create_llm_provider().generate(
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

        review = self._parse_review(raw_response)
        new_status = "completed" if review.get("approved") else "need_revision"
        TaskRepository.update_status(
            task["id"],
            new_status,
            review_result=review,
            review_feedback=review.get("feedback", ""),
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
        return review

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
            if isinstance(parsed, dict):
                return {"approved": bool(parsed.get("approved", True)), "feedback": parsed.get("feedback", "")}
        except json.JSONDecodeError:
            pass
        return {"approved": True, "feedback": "导师审核通过，但原始审核输出不是标准 JSON。"}


review_service = ReviewService()
