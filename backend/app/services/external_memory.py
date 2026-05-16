from __future__ import annotations

import uuid
from datetime import datetime

from ..storage.repositories import MemoryRecordRepository


class ExternalMemory:
    def write(
        self,
        run_id: str,
        scope: str,
        category: str,
        summary: str,
        *,
        agent_id: str | None = None,
        source_task_id: str | None = None,
        payload: dict | None = None,
    ) -> dict:
        now = datetime.now().isoformat()
        record = {
            "id": f"memory_{uuid.uuid4().hex[:10]}",
            "run_id": run_id,
            "agent_id": agent_id,
            "scope": scope,
            "category": category,
            "summary": summary,
            "payload": payload or {},
            "source_task_id": source_task_id,
            "created_at": now,
            "updated_at": now,
        }
        MemoryRecordRepository.insert(record)
        return record

    def save_summary(self, agent_id: str, content: str):
        raise NotImplementedError("请使用 write(run_id=..., scope='agent', ...) 写入结构化记忆")

    def retrieve(self, run_id: str, query: str, agent_id: str | None = None) -> list[dict]:
        return MemoryRecordRepository.search(run_id, query, agent_id=agent_id)

    def compact(self, run_id: str) -> list[dict]:
        return MemoryRecordRepository.get_by_run(run_id)

    def get_context(self, run_id: str, agent_id: str | None = None) -> dict:
        items = MemoryRecordRepository.get_by_run(run_id)
        return {
            "project": [item for item in items if item["scope"] == "project"],
            "agent": [item for item in items if item["scope"] == "agent" and (agent_id is None or item["agent_id"] == agent_id)],
        }


external_memory = ExternalMemory()
