import json
import uuid
from datetime import datetime

from ..core.llm_provider import create_llm_provider
from ..core.prompt_loader import prompt_loader
from ..models.task import TaskStatus
from ..storage.repositories import TaskRepository


class TaskDecomposer:
    async def decompose(self, research_goal: str, run_id: str) -> list[dict]:
        system_prompt = prompt_loader.load("advisor_agent")
        user_prompt = f"""请把下面的研究目标拆解为 3-7 个可执行任务。

研究目标：
{research_goal}

要求：
1. 每个任务必须包含 title、description、task_type、priority、complexity、decomposability、required_skills。
2. task_type 只能是 literature_survey、system_design、experiment_design、result_analysis、report_writing。
3. priority、complexity、decomposability 和 required_skills 中的技能分数均为 1-10。
4. 只返回合法 JSON 数组，不要输出解释性文字。
"""

        raw_response = await create_llm_provider().generate(
            prompt=f"{system_prompt}\n\n---\n\n{user_prompt}",
            schema={
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "task_type": {
                            "type": "string",
                            "enum": [
                                "literature_survey",
                                "system_design",
                                "experiment_design",
                                "result_analysis",
                                "report_writing",
                            ],
                        },
                        "priority": {"type": "integer", "minimum": 1, "maximum": 10},
                        "complexity": {"type": "integer", "minimum": 1, "maximum": 10},
                        "decomposability": {"type": "integer", "minimum": 1, "maximum": 10},
                        "required_skills": {"type": "object"},
                    },
                    "required": [
                        "title",
                        "description",
                        "task_type",
                        "priority",
                        "complexity",
                        "decomposability",
                        "required_skills",
                    ],
                },
            },
            role="advisor_decompose",
            run_id=run_id,
        )

        tasks_data = self._parse_response(raw_response)
        now = datetime.now().isoformat()
        tasks = []

        for item in tasks_data:
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            task = {
                "id": task_id,
                "title": item.get("title", "未命名任务"),
                "description": item.get("description", ""),
                "task_type": item.get("task_type", "literature_survey"),
                "required_skills": self._normalize_skills(item.get("required_skills", {})),
                "priority": self._bounded_int(item.get("priority", 5)),
                "complexity": self._bounded_int(item.get("complexity", 5)),
                "decomposability": self._bounded_int(item.get("decomposability", 5)),
                "status": TaskStatus.pending.value,
                "owner_agent": None,
                "collaborator_agents": [],
                "subtasks": [],
                "outputs": [],
                "review_result": None,
                "review_feedback": None,
                "run_id": run_id,
                "created_at": now,
                "updated_at": now,
            }
            TaskRepository.insert(task)
            tasks.append(task)

        return tasks

    def _parse_response(self, raw: str) -> list[dict]:
        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        try:
            parsed = json.loads(text.strip())
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []

    def _bounded_int(self, value: int, default: int = 5) -> int:
        try:
            return max(1, min(10, int(value)))
        except (TypeError, ValueError):
            return default

    def _normalize_skills(self, skills: dict) -> dict:
        keys = ["literature_review", "coding", "experiment", "data_analysis", "academic_writing", "mentoring"]
        return {key: self._bounded_int(skills.get(key, 1), default=1) for key in keys}


task_decomposer = TaskDecomposer()
