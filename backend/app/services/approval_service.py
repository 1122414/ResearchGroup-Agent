from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException

from ..storage.repositories import ApprovalRequestRepository, RunEventRepository


class ApprovalService:
    def ensure_pending(self, run_id: str, request_type: str, title: str, message: str, task_id: str | None = None, payload: dict | None = None) -> dict:
        existing = ApprovalRequestRepository.find_pending(run_id, request_type, task_id)
        if existing:
            return existing
        request = {
            "id": f"approval_{uuid.uuid4().hex[:10]}",
            "run_id": run_id,
            "task_id": task_id,
            "request_type": request_type,
            "status": "pending",
            "title": title,
            "message": message,
            "payload": payload or {},
            "created_at": datetime.now().isoformat(),
        }
        ApprovalRequestRepository.insert(request)
        RunEventRepository.insert(
            {
                "id": f"evt_{uuid.uuid4().hex[:10]}",
                "run_id": run_id,
                "task_id": task_id,
                "event_type": "approval.requested",
                "phase": "approval",
                "title": title,
                "message": message,
                "payload": {"request_id": request["id"], "request_type": request_type, **(payload or {})},
                "created_at": request["created_at"],
            }
        )
        return request

    def ensure_grouped_pending(
        self,
        run_id: str,
        request_type: str,
        dedupe_key: str,
        title: str,
        message: str,
        task_id: str,
        revision_task_id: str,
        task_title: str,
    ) -> dict:
        existing = ApprovalRequestRepository.find_pending_by_dedupe_key(run_id, request_type, dedupe_key)
        if existing:
            payload = dict(existing.get("payload") or {})
            task_ids = list(dict.fromkeys([*(payload.get("task_ids") or []), task_id]))
            revision_task_ids = list(dict.fromkeys([*(payload.get("revision_task_ids") or []), revision_task_id]))
            task_titles = list(dict.fromkeys([*(payload.get("task_titles") or []), task_title]))
            payload.update(
                {
                    "dedupe_key": dedupe_key,
                    "task_ids": task_ids,
                    "revision_task_ids": revision_task_ids,
                    "task_titles": task_titles,
                }
            )
            grouped_title = f"{title}（{len(task_ids)} 项）" if len(task_ids) > 1 else title
            ApprovalRequestRepository.update(existing["id"], title=grouped_title, message=message, payload=payload)
            return ApprovalRequestRepository.get_by_id(existing["id"]) or existing

        return self.ensure_pending(
            run_id,
            request_type,
            title,
            message,
            task_id=None,
            payload={
                "dedupe_key": dedupe_key,
                "task_ids": [task_id],
                "revision_task_ids": [revision_task_id],
                "task_titles": [task_title],
            },
        )

    def resolve(self, request_id: str, approved: bool, resolved_by: str = "user") -> dict:
        request = ApprovalRequestRepository.get_by_id(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="确认请求不存在")
        if request["status"] != "pending":
            return request
        status = "approved" if approved else "rejected"
        resolved_at = datetime.now().isoformat()
        ApprovalRequestRepository.update(request_id, status=status, resolved_at=resolved_at, resolved_by=resolved_by)
        updated = ApprovalRequestRepository.get_by_id(request_id)
        RunEventRepository.insert(
            {
                "id": f"evt_{uuid.uuid4().hex[:10]}",
                "run_id": request["run_id"],
                "task_id": request.get("task_id"),
                "event_type": "approval.resolved",
                "phase": "approval",
                "title": "确认已通过" if approved else "确认已拒绝",
                "message": request["title"],
                "payload": {"request_id": request_id, "request_type": request["request_type"], "approved": approved},
                "created_at": resolved_at,
            }
        )
        return updated


approval_service = ApprovalService()
