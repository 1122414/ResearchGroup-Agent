import json
from datetime import datetime

from ..core.llm_provider import create_llm_provider
from ..core.logger import logger
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import AgentRepository, OutputRepository, TaskRepository
from .agent_skill_service import agent_skill_service
from .external_memory import external_memory
from .literature_source_service import literature_source_service
from .reproducible_experiment_service import reproducible_experiment_service


class TaskExecutor:
    async def execute(self, task: dict) -> dict:
        task_title = task.get("title", "")
        task_type = task.get("task_type", "literature_survey")
        owner_id = task.get("owner_agent", "")
        owner = AgentRepository.get_by_id(owner_id) if owner_id else None
        agent_type = owner.get("type", "researcher") if owner else "researcher"
        logger.info("[TaskExecutor] execute started | task_id=%s | type=%s | agent=%s", task.get("id"), task_type, agent_type)

        prompt_map = {
            "researcher": "grad_researcher",
            "engineer": "grad_engineer",
            "experimenter": "grad_experimenter",
            "analyst": "grad_analyst",
            "writer": "grad_writer",
        }
        system_prompt = prompt_loader.load(prompt_map.get(agent_type, "grad_researcher"))
        active_skills = agent_skill_service.active_for_task(owner_id, task)
        skill_prompt = agent_skill_service.render_for_prompt(active_skills)
        user_prompt = f"""请以 {agent_type} 研究生 Agent 的身份完成下面任务，并返回合法 JSON。

任务标题：{task_title}
任务类型：{task_type}
任务描述：{task.get("description", "")}

{skill_prompt}

输出要求：
1. 给出 summary。
2. 给出 findings 或 deliverables。
3. 给出 risks 或 next_steps。
4. 不要输出 Markdown，只返回 JSON。
"""

        llm = create_llm_provider()
        prompt_len = len(system_prompt) + len(user_prompt)
        logger.info("[TaskExecutor] calling LLM | task_id=%s | role=graduate | prompt_len=%d | active_skills=%d", task.get("id"), prompt_len, len(active_skills))
        try:
            raw_response = await llm.generate(
                prompt=f"{system_prompt}\n\n---\n\n{user_prompt}",
                role="graduate",
                run_id=task.get("run_id"),
                task_id=task.get("id"),
                agent_id=owner_id,
            )
        except Exception:
            agent_skill_service.record_usage(active_skills, success=False)
            raise
        result = self._parse_result(raw_response)
        if task_type == "literature_survey":
            result = literature_source_service.enrich_result(task, result)
        if task_type == "experiment_design":
            experiment_result = reproducible_experiment_service.run_for_task(task, owner_id)
            result = {**result, "reproducible_experiment": experiment_result}
        if active_skills:
            result["used_skills"] = [
                {
                    "id": skill["id"],
                    "title": skill["title"],
                    "usage_count_before": skill.get("usage_count", 0),
                    "last_used_at_before": skill.get("last_used_at"),
                }
                for skill in active_skills
            ]
            agent_skill_service.record_usage(active_skills, success=True)
        logger.info("[TaskExecutor] LLM response parsed | task_id=%s | has_summary=%s", task.get("id"), "summary" in result)
        TaskRepository.update_status(task["id"], "running", outputs=task.get("outputs", []) + [result])
        self._write_memory(task, owner_id, result)

        OutputRepository.insert(
            {
                "id": f"out_{task['id']}",
                "output_type": "task_result",
                "title": f"任务产出：{task_title}",
                "content": json.dumps(result, ensure_ascii=False, indent=2),
                "run_id": task.get("run_id"),
                "task_id": task["id"],
                "agent_id": owner_id,
                "created_at": datetime.now().isoformat(),
            }
        )
        logger.info("[TaskExecutor] execute completed | task_id=%s | output_saved=%s", task.get("id"), f"out_{task['id']}")
        return result

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
            return {"raw_output": text, "parsed": False}

    def _write_memory(self, task: dict, owner_id: str, result: dict) -> None:
        run_id = task.get("run_id")
        if not run_id:
            return
        summary = str(result.get("summary") or result.get("conclusion") or task.get("title") or "")
        if summary:
            external_memory.write(
                run_id,
                "project",
                task.get("task_type", "task"),
                summary[:500],
                source_task_id=task.get("id"),
                payload={"task_title": task.get("title"), "task_type": task.get("task_type")},
            )
            external_memory.write(
                run_id,
                "agent",
                "task_experience",
                summary[:500],
                agent_id=owner_id or None,
                source_task_id=task.get("id"),
                payload={"task_title": task.get("title"), "task_type": task.get("task_type")},
            )


task_executor = TaskExecutor()
