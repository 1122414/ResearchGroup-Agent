import uuid
from datetime import datetime

from ..storage.repositories import RunEventRepository


class RunEventService:
    def emit(
        self,
        run_id: str,
        event_type: str,
        phase: str,
        title: str,
        message: str = "",
        task_id: str | None = None,
        agent_id: str | None = None,
        subagent_id: str | None = None,
        payload: dict | None = None,
    ) -> dict:
        event = {
            "id": f"evt_{uuid.uuid4().hex[:10]}",
            "run_id": run_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "subagent_id": subagent_id,
            "event_type": event_type,
            "phase": phase,
            "title": title,
            "message": message,
            "payload": payload or {},
            "created_at": datetime.now().isoformat(),
        }
        RunEventRepository.insert(event)
        return event


run_event_service = RunEventService()
