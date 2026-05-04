import json
from datetime import datetime
from ..core.llm_provider import create_llm_provider
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import TaskRepository, AgentRepository, OutputRepository


class TaskExecutor:
    def __init__(self):
        self._llm = create_llm_provider()

    async def execute(self, task: dict) -> dict:
        task_type = task.get("task_type", "literature_survey")
        task_title = task.get("title", "")
        task_desc = task.get("description", "")

        prompt_map = {
            "researcher": "grad_researcher",
            "engineer": "grad_engineer",
            "experimenter": "grad_experimenter",
            "analyst": "grad_analyst",
            "writer": "grad_writer",
        }

        owner_id = task.get("owner_agent", "")
        owner = AgentRepository.get_by_id(owner_id) if owner_id else None
        agent_type = owner.get("type", "researcher") if owner else "researcher"
        prompt_name = prompt_map.get(agent_type, "grad_researcher")

        system_prompt = prompt_loader.load(prompt_name)
        user_prompt = f"""请执行以下任务并返回结构化结果：

任务标题：{task_title}
任务类型：{task_type}
任务描述：{task_desc}
你的角色：{agent_type}

请以 JSON 格式返回结果，包含你的分析、发现和建议。"""

        full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        raw_response = await self._llm.generate(prompt=full_prompt, role="graduate")

        result = self._parse_result(raw_response)
        TaskRepository.update_status(task["id"], "running", outputs=task.get("outputs", []) + [result])

        output_id = f"out_{task['id']}"
        OutputRepository.insert({
            "id": output_id,
            "output_type": "task_result",
            "title": f"任务结果: {task_title}",
            "content": json.dumps(result, ensure_ascii=False, indent=2),
            "run_id": task.get("run_id"),
            "task_id": task["id"],
            "agent_id": owner_id,
            "created_at": datetime.now().isoformat(),
        })

        return result

    def _parse_result(self, raw: str) -> dict:
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
            return {"raw_output": raw, "parsed": False}


task_executor = TaskExecutor()
