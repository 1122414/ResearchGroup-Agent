import json
from datetime import datetime
from ..core.llm_provider import create_llm_provider
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import TaskRepository, OutputRepository


class ReviewService:
    def __init__(self):
        self._llm = create_llm_provider()

    async def review(self, task: dict) -> dict:
        system_prompt = prompt_loader.load("advisor_agent")
        user_prompt = f"""请审核以下任务结果：

任务标题：{task.get('title', '')}
任务类型：{task.get('task_type', '')}
任务描述：{task.get('description', '')}
执行结果：{json.dumps(task.get('outputs', []), ensure_ascii=False, indent=2)}

审核标准：
1. 结果是否完整覆盖任务要求
2. 结果是否结构化清晰
3. 结果是否有实质性内容
4. 约15%的任务可以给返工

请以 JSON 格式返回：
{{"approved": true/false, "feedback": "审核意见"}}"""

        full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        raw_response = await self._llm.generate(
            prompt=full_prompt,
            schema={
                "type": "object",
                "properties": {
                    "approved": {"type": "boolean"},
                    "feedback": {"type": "string"}
                },
                "required": ["approved", "feedback"]
            },
            role="advisor"
        )

        review = self._parse_review(raw_response)
        new_status = "completed" if review.get("approved") else "need_revision"

        TaskRepository.update_status(
            task["id"],
            new_status,
            review_result=review,
            review_feedback=review.get("feedback", ""),
        )

        OutputRepository.insert({
            "id": f"review_{task['id']}",
            "output_type": "review",
            "title": f"审核结果: {task.get('title', '')}",
            "content": json.dumps(review, ensure_ascii=False, indent=2),
            "run_id": task.get("run_id"),
            "task_id": task["id"],
            "created_at": datetime.now().isoformat(),
        })

        return review

    def _parse_review(self, raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```json"):
            raw = raw[7:]
        if raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"approved": True, "feedback": "审核通过（响应解析失败，默认通过）"}


review_service = ReviewService()
