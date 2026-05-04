import json
import uuid
from datetime import datetime
from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import SubAgentRepository, TaskRepository, OutputRepository, AgentRepository
from ..models.agent import AgentStatus


class SubAgentService:
    def __init__(self):
        self._llm = create_llm_provider()

    def can_create_subagent(self, task: dict, agent: dict) -> bool:
        complexity = task.get("complexity", 5)
        decomposability = task.get("decomposability", 5)
        mentoring = agent.get("skills", {}).get("mentoring", 1)
        return (
            complexity >= settings.subagent_complexity_threshold
            and decomposability >= settings.subagent_decomposability_threshold
            and mentoring >= settings.subagent_mentoring_threshold
        )

    def max_subagents(self, agent: dict) -> int:
        mentoring = agent.get("skills", {}).get("mentoring", 1)
        return max(0, mentoring // 3)

    async def create_and_execute(self, parent_agent_id: str, task: dict) -> dict | None:
        agent = AgentRepository.get_by_id(parent_agent_id)
        if not agent or not self.can_create_subagent(task, agent):
            return None

        existing_subs = SubAgentRepository.get_by_task(task["id"])
        max_subs = self.max_subagents(agent)
        if len(existing_subs) >= max_subs:
            return None

        sub_id = f"subagent_{uuid.uuid4().hex[:8]}"
        sub_task_description = self._build_sub_task(task)
        expected_schema = {
            "type": "object",
            "properties": {
                "findings": {"type": "array", "items": {"type": "object"}},
                "summary": {"type": "string"}
            }
        }

        subagent = {
            "id": sub_id,
            "parent_agent": parent_agent_id,
            "task_id": task["id"],
            "task": sub_task_description,
            "context": f"这是任务「{task.get('title', '')}」的子任务",
            "expected_output_schema": expected_schema,
            "status": "running",
            "lifecycle": "destroy_after_return",
            "result": None,
        }
        SubAgentRepository.insert(subagent)

        TaskRepository.update_status(task["id"], "waiting_subagent")

        system_prompt = prompt_loader.load("subagent")
        user_prompt = f"""请完成以下子任务并返回结构化结果：

子任务：{sub_task_description}
任务上下文：{task.get('title', '')} - {task.get('description', '')}

请以如下 JSON Schema 返回结果：
{json.dumps(expected_schema, ensure_ascii=False, indent=2)}

只返回 JSON，不要其他内容。"""

        full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        raw_response = await self._llm.generate(prompt=full_prompt, schema=expected_schema, role="subagent")

        result = self._parse_result(raw_response)
        SubAgentRepository.update_result(sub_id, result)

        OutputRepository.insert({
            "id": f"out_{sub_id}",
            "output_type": "subagent_result",
            "title": f"SubAgent结果: {sub_task_description[:50]}",
            "content": json.dumps(result, ensure_ascii=False, indent=2),
            "run_id": task.get("run_id"),
            "task_id": task["id"],
            "agent_id": parent_agent_id,
            "created_at": datetime.now().isoformat(),
        })

        return result

    def _build_sub_task(self, task: dict) -> str:
        task_type = task.get("task_type", "")
        task_title = task.get("title", "")
        if task_type == "literature_survey":
            return f"搜索与「{task_title}」相关的5个项目或论文，整理名称、链接、功能和技术栈"
        elif task_type == "system_design":
            return f"搜索与「{task_title}」相关的3个开源系统架构参考，整理技术选型"
        else:
            return f"协助完成「{task_title}」的数据收集和整理工作"

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
            return {"raw_output": raw}


subagent_service = SubAgentService()
