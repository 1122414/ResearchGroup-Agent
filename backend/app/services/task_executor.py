import json
from datetime import datetime

from ..core.config import settings
from ..core.llm_provider import create_llm_provider
from ..core.logger import logger
from ..core.prompt_loader import prompt_loader
from ..storage.repositories import AgentRepository, OutputRepository, SubAgentRepository, TaskRepository
from .agent_skill_service import agent_skill_service
from .external_memory import external_memory
from .evidence_pipeline_service import evidence_pipeline_service
from .knowledge_graph_service import knowledge_graph_service
from .literature_source_service import literature_source_service
from .research_integrity_service import research_integrity_service
from .reproducible_experiment_service import reproducible_experiment_service
from .run_event_service import run_event_service


class TaskExecutor:
    RESULT_SCHEMA = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "string"},
                        "evidence_source_ids": {"type": "array", "items": {"type": "string"}},
                        "evidence_passage_ids": {"type": "array", "items": {"type": "string"}},
                        "relation": {"type": "string", "enum": ["supports", "opposes", "context"]},
                        "confidence": {"type": "number"},
                    },
                    "required": ["statement", "evidence_source_ids", "evidence_passage_ids", "relation", "confidence"],
                },
            },
        },
        "required": ["summary", "claims"],
    }

    async def execute(self, task: dict) -> dict:
        task_title = task.get("title", "")
        task_type = task.get("task_type", "literature_survey")
        owner_id = task.get("owner_agent", "")
        owner = AgentRepository.get_by_id(owner_id) if owner_id else None
        agent_type = owner.get("type", "researcher") if owner else "researcher"
        logger.info("[TaskExecutor] execute started | task_id=%s | type=%s | agent=%s", task.get("id"), task_type, agent_type)
        evidence_bundle = await evidence_pipeline_service.collect_for_task(task) if task_type == "literature_survey" else None

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
        collaboration_context = self._collaboration_context(task)
        literature_grounding = ""
        if evidence_bundle is not None:
            required_source_count = research_integrity_service.required_grounded_source_count(task, evidence_bundle["query"])
            literature_grounding = f"""

【学术诚信与证据边界】
1. 你只能基于下方 allowed_sources 归纳，不得补写、猜测或伪造任何论文、作者、年份、DOI、URL。
2. 若来源不足以回答任务，请明确输出“证据不足”，不要为了完整性编造结论。
3. 只允许通过 source_id 引用，格式为 [source_id]；不要自行生成参考文献列表。
4. 每条结论必须同时给出 source_id 与对应 passage_id；没有 passage 的来源只能用于检索线索，不能支撑结论。
5. 输出 JSON 中必须包含 references_used，且每一项都只能来自 allowed_sources.source_id。
6. 当前检索 query：{evidence_bundle["query"]}
7. allowed_sources（含可引用 passages）：
当前任务所需最少可核验来源数：{required_source_count}
{research_integrity_service.render_allowed_sources(evidence_bundle["sources"], evidence_bundle["excerpts"])}
"""
        user_prompt = f"""请以 {agent_type} 研究生 Agent 的身份完成下面任务，并返回合法 JSON。

任务标题：{task_title}
任务类型：{task_type}
任务描述：{task.get("description", "")}

{skill_prompt}
{collaboration_context}
{literature_grounding}

输出要求：
1. 给出 summary。
2. 给出 findings 或 deliverables。
3. 给出 risks 或 next_steps。
4. 给出 claims：数组，每个元素 {{"statement": 可单独核验的研究性结论, "evidence_source_ids": [来源ID], "evidence_passage_ids": [该来源下的原文片段ID], "relation": "supports"|"opposes"|"context", "confidence": 0到1}}。没有可定位片段时不要输出该 claim。
5. 给出 hypotheses（可选）：数组，每个元素 {{"statement": 可检验的假设, "rationale": 依据}}。
6. 给出 uncertainties（可选）：数组，每个元素 {{"description": 仍未解决的问题, "severity": "low"|"medium"|"high"}}。
7. 不要输出 Markdown，只返回 JSON。
"""

        llm = create_llm_provider()
        prompt_len = len(system_prompt) + len(user_prompt)
        logger.info("[TaskExecutor] calling LLM | task_id=%s | role=graduate | prompt_len=%d | active_skills=%d", task.get("id"), prompt_len, len(active_skills))
        prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        try:
            result = await self._generate_structured(llm, prompt, task, owner_id)
        except Exception:
            agent_skill_service.record_usage(active_skills, success=False)
            raise
        if task_type == "literature_survey" and evidence_bundle is not None:
            result = research_integrity_service.apply_literature_policy(
                result,
                evidence_bundle["sources"],
                evidence_bundle["query"],
                evidence_bundle["mode"],
                task,
                evidence_bundle["excerpts"],
            )
            methods = literature_source_service.methods_from_sources(evidence_bundle["sources"])
            artifacts = literature_source_service.write_artifacts(task, evidence_bundle["sources"], methods)
            result = {
                **result,
                "source_mode": evidence_bundle["mode"],
                "papers_read": evidence_bundle["sources"],
                "methods_found": methods,
                "evidence_excerpts": evidence_bundle["excerpts"],
                "evidence_assessments": evidence_bundle["assessments"],
                "source_artifacts": artifacts,
            }
        if task_type == "experiment_design":
            experiment_result = await reproducible_experiment_service.run_for_task(task, owner_id)
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
        graph = knowledge_graph_service.ingest_task_result(task, result)
        # evidence_links is a count (int), not a collection — see knowledge_graph_service.
        evidence_link_count = graph.get("evidence_links") or 0
        if not isinstance(evidence_link_count, int):
            evidence_link_count = len(evidence_link_count)
        if graph["claims"] or graph["hypotheses"] or graph["uncertainties"]:
            result = {
                **result,
                "knowledge_graph": {
                    "claim_ids": [item["id"] for item in graph["claims"] if item],
                    "hypothesis_ids": [item["id"] for item in graph["hypotheses"]],
                    "uncertainty_ids": [item["id"] for item in graph["uncertainties"]],
                    "evidence_links": evidence_link_count,
                },
            }
            run_event_service.emit(
                task.get("run_id"),
                "knowledge_graph.updated",
                "execute",
                "知识图谱已更新",
                f"新增结论 {len(graph['claims'])} 条、假设 {len(graph['hypotheses'])} 条、证据关联 {evidence_link_count} 条",
                task_id=task.get("id"),
                agent_id=owner_id,
                payload={
                    "claims": len(graph["claims"]),
                    "hypotheses": len(graph["hypotheses"]),
                    "evidence_links": evidence_link_count,
                },
            )
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

    def _collaboration_context(self, task: dict) -> str:
        """Surface SubAgent/collaborator results so the owner integrates them.

        Previously a SubAgent ran and its result was stored, but the owner's LLM
        call never consumed it, so collaboration was cosmetic. Here we inject any
        SubAgent results and collaborator roster into the owner prompt and require
        their integration before the task output is reviewed.
        """
        subagent_results = [
            sub["result"]
            for sub in SubAgentRepository.get_by_task(task["id"])
            if isinstance(sub.get("result"), (dict, list)) and sub.get("result")
        ]
        collaborators = task.get("collaborator_agents", []) or []
        if not subagent_results and not collaborators:
            return ""
        parts = ["【协作中间结果（必须整合，不得忽略）】"]
        if collaborators:
            parts.append(f"协作 Agent：{', '.join(str(item) for item in collaborators)}")
        if subagent_results:
            parts.append("SubAgent 返回的中间结果：")
            parts.append(json.dumps(subagent_results, ensure_ascii=False, indent=2)[:4000])
        parts.append("请在 summary 与 claims 中明确说明你如何整合上述协作结果，不要简单复制。")
        return "\n".join(parts)

    async def _generate_structured(self, llm, prompt: str, task: dict, owner_id: str) -> dict:
        attempts = min(max(int(settings.llm_structured_repair_attempts), 0), 2) + 1
        current_prompt = prompt
        last_error = ""
        for attempt in range(attempts):
            raw = await llm.generate(
                prompt=current_prompt,
                schema=self.RESULT_SCHEMA,
                role="graduate",
                run_id=task.get("run_id"),
                task_id=task.get("id"),
                agent_id=owner_id,
            )
            try:
                return self._parse_result(raw)
            except ValueError as exc:
                last_error = str(exc)
                if attempt + 1 >= attempts:
                    break
                current_prompt = (
                    f"{prompt}\n\n上一次输出未通过结构校验（{last_error}）。"
                    "请只修复 JSON 结构，不新增事实；无法提供证据的 claims 必须删除。\n"
                    f"待修复输出：{raw[:4000]}"
                )
        raise ValueError(f"LLM structured output invalid after {attempts} attempt(s): {last_error}")

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
        except json.JSONDecodeError as exc:
            raise ValueError("response is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("response root must be an object")
        if not str(parsed.get("summary") or "").strip():
            raise ValueError("summary is required")
        if not isinstance(parsed.get("claims"), list):
            raise ValueError("claims must be an array")
        return parsed

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
