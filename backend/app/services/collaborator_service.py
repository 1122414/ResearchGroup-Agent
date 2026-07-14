from __future__ import annotations

import asyncio
import json
from datetime import datetime

from ..core.llm_provider import create_llm_provider
from ..storage.repositories import AgentRepository, OutputRepository
from .run_event_service import run_event_service


class CollaboratorService:
    SCHEMA = {
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
                    },
                    "required": ["statement", "evidence_source_ids", "evidence_passage_ids"],
                },
            },
            "contradictions": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "claims", "contradictions", "risks"],
    }

    async def execute_all(self, task: dict, evidence_context: str = "") -> list[dict]:
        collaborator_ids = list(dict.fromkeys(task.get("collaborator_agents") or []))
        if not collaborator_ids:
            return []
        results = await asyncio.gather(
            *(self._execute_one(task, collaborator_id, evidence_context) for collaborator_id in collaborator_ids),
            return_exceptions=True,
        )
        accepted: list[dict] = []
        for collaborator_id, result in zip(collaborator_ids, results):
            if isinstance(result, Exception):
                run_event_service.emit(
                    task.get("run_id"), "collaborator.failed", "collaboration", "独立协作者执行失败",
                    str(result), task_id=task.get("id"), agent_id=collaborator_id,
                )
                continue
            accepted.append(result)
        return accepted

    async def _execute_one(self, task: dict, collaborator_id: str, evidence_context: str) -> dict:
        agent = AgentRepository.get_by_id(collaborator_id) or {}
        role = str(agent.get("type") or "researcher")
        prompt = f"""你是独立协作者，不是父任务作者。请独立完成一个有边界的批判子任务。

父任务：{task.get('title', '')}
任务说明：{task.get('description', '')}
你的角色：{role}

要求：
1. 只检查证据缺口、矛盾、方法风险或统计风险，不改写父任务目标。
2. 有证据上下文时，claim 只能使用其中已有 source_id 和 passage_id；没有时 claims 必须为空。
3. 不得提出或编造未提供来源的论文、作者、DOI、URL。
4. 返回合法 JSON：summary、claims、contradictions、risks。

证据上下文：
{evidence_context[:12000] if evidence_context else '无；不得形成事实性 claim。'}
"""
        raw = await create_llm_provider().generate(
            prompt=prompt, schema=self.SCHEMA, role="graduate", run_id=task.get("run_id"),
            task_id=task.get("id"), agent_id=collaborator_id,
        )
        parsed = self._parse(raw)
        parsed["claims"] = self._sanitize_claims(parsed["claims"], evidence_context)
        result = {"collaborator_id": collaborator_id, "role": role, "output": parsed}
        OutputRepository.insert(
            {
                "id": f"out_collab_{task['id']}_{collaborator_id}", "output_type": "collaborator_result",
                "title": f"独立协作者产出：{task.get('title', '')}",
                "content": json.dumps(parsed, ensure_ascii=False, indent=2), "run_id": task.get("run_id"),
                "task_id": task["id"], "agent_id": collaborator_id, "created_at": datetime.now().isoformat(),
            }
        )
        run_event_service.emit(
            task.get("run_id"), "collaborator.completed", "collaboration", "独立协作者已提交产出",
            parsed["summary"], task_id=task.get("id"), agent_id=collaborator_id,
            payload={"output_id": f"out_collab_{task['id']}_{collaborator_id}", "role": role},
        )
        return result

    @staticmethod
    def _parse(raw: str) -> dict:
        text = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        value = json.loads(text)
        if not isinstance(value, dict) or not str(value.get("summary") or "").strip():
            raise ValueError("collaborator output must be a JSON object with summary")
        for key in ("claims", "contradictions", "risks"):
            if not isinstance(value.get(key), list):
                raise ValueError(f"collaborator output {key} must be an array")
        return value

    @staticmethod
    def _sanitize_claims(claims: list[dict], evidence_context: str) -> list[dict]:
        if not evidence_context:
            return []
        accepted = []
        for claim in claims:
            source_ids = claim.get("evidence_source_ids") or []
            passage_ids = claim.get("evidence_passage_ids") or []
            if source_ids and passage_ids and all(str(item) in evidence_context for item in [*source_ids, *passage_ids]):
                accepted.append(claim)
        return accepted


collaborator_service = CollaboratorService()
