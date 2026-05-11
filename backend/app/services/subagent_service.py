import json
import uuid
from datetime import datetime

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.logger import logger
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import AgentRepository, OutputRepository, SubAgentRepository, TaskRepository


class SubAgentService:
    def can_create_subagent(self, task: dict, agent: dict) -> bool:
        result = (
            task.get("complexity", 5) >= settings.subagent_complexity_threshold
            and task.get("decomposability", 5) >= settings.subagent_decomposability_threshold
            and agent.get("skills", {}).get("mentoring", 1) >= settings.subagent_mentoring_threshold
        )
        logger.debug("[SubAgentService] can_create_subagent | task_id=%s | result=%s", task.get("id"), result)
        return result

    def max_subagents(self, agent: dict) -> int:
        return max(0, agent.get("skills", {}).get("mentoring", 1) // 3)

    async def create_and_execute(self, parent_agent_id: str, task: dict) -> dict | None:
        logger.info("[SubAgentService] create_and_execute | task_id=%s | parent=%s", task.get("id"), parent_agent_id)
        agent = AgentRepository.get_by_id(parent_agent_id)
        if not agent or not self.can_create_subagent(task, agent):
            logger.info("[SubAgentService] subagent not allowed | task_id=%s", task.get("id"))
            return None

        existing_subs = SubAgentRepository.get_by_task(task["id"])
        if len(existing_subs) >= self.max_subagents(agent):
            logger.info("[SubAgentService] max subagents reached | task_id=%s | count=%d", task.get("id"), len(existing_subs))
            return None

        sub_id = f"subagent_{uuid.uuid4().hex[:8]}"
        sub_task_description = self._build_sub_task(task)
        expected_schema = {
            "type": "object",
            "properties": {
                "findings": {"type": "array", "items": {"type": "object"}},
                "summary": {"type": "string"},
            },
        }

        subagent = {
            "id": sub_id,
            "parent_agent": parent_agent_id,
            "task_id": task["id"],
            "task": sub_task_description,
            "context": f"父任务：{task.get('title', '')}",
            "expected_output_schema": expected_schema,
            "status": "running",
            "lifecycle": "destroy_after_return",
            "result": None,
        }
        SubAgentRepository.insert(subagent)
        TaskRepository.update_status(task["id"], "waiting_subagent")
        logger.info("[SubAgentService] subagent inserted | sub_id=%s | task_id=%s", sub_id, task["id"])

        system_prompt = prompt_loader.load("subagent")
        user_prompt = f"""你是一个临时 SubAgent，只能完成父 Agent 委派的小任务。

子任务：{sub_task_description}
父任务：{task.get('title', '')}
父任务说明：{task.get('description', '')}

请返回 JSON，包含 findings 和 summary。不要改变父任务目标，不要创建新的 Agent。
"""

        llm = create_llm_provider()
        logger.info("[SubAgentService] calling LLM | sub_id=%s | role=subagent", sub_id)
        raw_response = await llm.generate(
            prompt=f"{system_prompt}\n\n---\n\n{user_prompt}",
            schema=expected_schema,
            role="subagent",
            run_id=task.get("run_id"),
            task_id=task["id"],
            agent_id=parent_agent_id,
        )
        result = self._parse_result(raw_response)
        logger.info("[SubAgentService] LLM response parsed | sub_id=%s | has_findings=%s | result_keys=%s",
                    sub_id, "findings" in result, list(result.keys()))
        SubAgentRepository.update_result(sub_id, result)

        OutputRepository.insert(
            {
                "id": f"out_{sub_id}",
                "output_type": "subagent_result",
                "title": f"SubAgent 产出：{sub_task_description[:50]}",
                "content": json.dumps(result, ensure_ascii=False, indent=2),
                "run_id": task.get("run_id"),
                "task_id": task["id"],
                "agent_id": parent_agent_id,
                "created_at": datetime.now().isoformat(),
            }
        )
        logger.info("[SubAgentService] create_and_execute completed | sub_id=%s | output_saved=%s", sub_id, f"out_{sub_id}")
        return result

    def _build_sub_task(self, task: dict) -> str:
        task_type = task.get("task_type", "")
        task_title = task.get("title", "")
        if task_type == "literature_survey":
            return f"为“{task_title}”补充 3 条相关工作或参考方向"
        if task_type == "system_design":
            return f"为“{task_title}”列出 3 个关键接口和风险点"
        if task_type == "experiment_design":
            return f"为“{task_title}”补充评测指标和验证步骤"
        return f"为“{task_title}”补充辅助分析材料"

    def _parse_result(self, raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        try:
            parsed = json.loads(text.strip())
            return parsed if isinstance(parsed, dict) else {"items": parsed}
        except json.JSONDecodeError:
            return {"raw_output": text}


subagent_service = SubAgentService()
