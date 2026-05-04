import json
import uuid
from datetime import datetime
from ..core.llm_provider import create_llm_provider
from ..core.prompt_loader import prompt_loader
from ..models.task import TaskCreate, TaskStatus, Task
from ..storage.repositories import TaskRepository


class TaskDecomposer:
    def __init__(self):
        self._llm = create_llm_provider()

    async def decompose(self, research_goal: str, run_id: str) -> list[dict]:
        system_prompt = prompt_loader.load("advisor_agent")
        user_prompt = f"""请将以下研究目标拆解为结构化任务列表：

研究目标：{research_goal}

要求：
1. 生成 3-7 个任务
2. 每个任务包含 title、description、task_type、priority、complexity、decomposability、required_skills
3. 任务要有层次：先调研、再设计、再实验、再分析、最后汇总
4. required_skills 每项 1-10 分
5. 只输出 JSON 数组，不要其他内容"""

        full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        raw_response = await self._llm.generate(
            prompt=full_prompt,
            schema={
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "task_type": {"type": "string", "enum": ["literature_survey", "system_design", "experiment_design", "result_analysis", "report_writing"]},
                        "priority": {"type": "integer", "minimum": 1, "maximum": 10},
                        "complexity": {"type": "integer", "minimum": 1, "maximum": 10},
                        "decomposability": {"type": "integer", "minimum": 1, "maximum": 10},
                        "required_skills": {
                            "type": "object",
                            "properties": {
                                "literature_review": {"type": "integer", "minimum": 1, "maximum": 10},
                                "coding": {"type": "integer", "minimum": 1, "maximum": 10},
                                "experiment": {"type": "integer", "minimum": 1, "maximum": 10},
                                "data_analysis": {"type": "integer", "minimum": 1, "maximum": 10},
                                "academic_writing": {"type": "integer", "minimum": 1, "maximum": 10},
                                "mentoring": {"type": "integer", "minimum": 1, "maximum": 10},
                            },
                            "required": ["literature_review", "coding", "experiment", "data_analysis", "academic_writing", "mentoring"]
                        }
                    },
                    "required": ["title", "description", "task_type", "priority", "complexity", "decomposability", "required_skills"]
                }
            },
            role="advisor"
        )

        tasks_data = self._parse_response(raw_response)
        tasks = []
        now = datetime.now().isoformat()

        for t in tasks_data:
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            task = {
                "id": task_id,
                "title": t.get("title", "未命名任务"),
                "description": t.get("description", ""),
                "task_type": t.get("task_type", "literature_survey"),
                "required_skills": t.get("required_skills", {}),
                "priority": max(1, min(10, t.get("priority", 5))),
                "complexity": max(1, min(10, t.get("complexity", 5))),
                "decomposability": max(1, min(10, t.get("decomposability", 5))),
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
            return []


task_decomposer = TaskDecomposer()
