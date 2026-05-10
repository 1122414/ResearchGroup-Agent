import json
from datetime import datetime
from typing import Optional

from .db import get_connection


class AgentRepository:
    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM agents").fetchall()
        conn.close()
        return [_deserialize_agent(row) for row in rows]

    @staticmethod
    def get_by_id(agent_id: str) -> Optional[dict]:
        conn = get_connection()
        row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        conn.close()
        return _deserialize_agent(row) if row else None

    @staticmethod
    def upsert(agent: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO agents (
                id, name, type, description, skills, status, current_load, max_load,
                current_tasks, preferred_task_types, tools, can_create_subagents, max_subagents
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent["id"],
                agent["name"],
                agent["type"],
                agent["description"],
                json.dumps(agent["skills"], ensure_ascii=False),
                agent.get("status", "idle"),
                agent.get("current_load", 0.0),
                agent.get("max_load", 1.0),
                json.dumps(agent.get("current_tasks", []), ensure_ascii=False),
                json.dumps(agent.get("preferred_task_types", []), ensure_ascii=False),
                json.dumps(agent.get("tools", []), ensure_ascii=False),
                int(agent.get("can_create_subagents", True)),
                agent.get("max_subagents", 0),
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def update_status(agent_id: str, status: str, current_load: float = 0.0, current_tasks: list[str] | None = None):
        conn = get_connection()
        if current_tasks is None:
            conn.execute("UPDATE agents SET status = ?, current_load = ? WHERE id = ?", (status, current_load, agent_id))
        else:
            conn.execute(
                "UPDATE agents SET status = ?, current_load = ?, current_tasks = ? WHERE id = ?",
                (status, current_load, json.dumps(current_tasks, ensure_ascii=False), agent_id),
            )
        conn.commit()
        conn.close()

    @staticmethod
    def seed(agents: list[dict]):
        for agent in agents:
            AgentRepository.upsert(agent)


class TaskRepository:
    @staticmethod
    def get_all(run_id: Optional[str] = None) -> list[dict]:
        conn = get_connection()
        if run_id:
            rows = conn.execute("SELECT * FROM tasks WHERE run_id = ? ORDER BY priority DESC", (run_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM tasks ORDER BY priority DESC").fetchall()
        conn.close()
        return [_deserialize_task(row) for row in rows]

    @staticmethod
    def get_by_id(task_id: str) -> Optional[dict]:
        conn = get_connection()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        return _deserialize_task(row) if row else None

    @staticmethod
    def insert(task: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO tasks (
                id, title, description, task_type, required_skills, priority, complexity,
                decomposability, status, owner_agent, collaborator_agents, subtasks, outputs,
                review_result, review_feedback, run_id, assignment_info, subagent_triggered, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["id"],
                task["title"],
                task.get("description", ""),
                task["task_type"],
                json.dumps(task["required_skills"], ensure_ascii=False),
                task.get("priority", 5),
                task.get("complexity", 5),
                task.get("decomposability", 5),
                task.get("status", "pending"),
                task.get("owner_agent"),
                json.dumps(task.get("collaborator_agents", []), ensure_ascii=False),
                json.dumps(task.get("subtasks", []), ensure_ascii=False),
                json.dumps(task.get("outputs", []), ensure_ascii=False),
                json.dumps(task.get("review_result"), ensure_ascii=False) if task.get("review_result") else None,
                task.get("review_feedback"),
                task.get("run_id"),
                json.dumps(task.get("assignment_info", {}), ensure_ascii=False),
                int(task.get("subagent_triggered", False)),
                task["created_at"],
                task["updated_at"],
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def update_status(task_id: str, status: str, **kwargs):
        conn = get_connection()
        updates = ["status = ?", "updated_at = ?"]
        params: list = [status, datetime.now().isoformat()]
        for key, value in kwargs.items():
            if key in ("outputs", "collaborator_agents", "subtasks", "assignment_info"):
                updates.append(f"{key} = ?")
                params.append(json.dumps(value, ensure_ascii=False))
            elif key == "subagent_triggered":
                updates.append(f"{key} = ?")
                params.append(int(value))
            elif key == "review_result":
                updates.append(f"{key} = ?")
                params.append(json.dumps(value, ensure_ascii=False) if value else None)
            elif key in ("owner_agent", "review_feedback", "run_id"):
                updates.append(f"{key} = ?")
                params.append(value)
        params.append(task_id)
        conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        conn.close()


class SubAgentRepository:
    @staticmethod
    def get_by_task(task_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM subagents WHERE task_id = ?", (task_id,)).fetchall()
        conn.close()
        return [_deserialize_subagent(row) for row in rows]

    @staticmethod
    def get_by_run(run_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT s.* FROM subagents s
            JOIN tasks t ON t.id = s.task_id
            WHERE t.run_id = ?
            """,
            (run_id,),
        ).fetchall()
        conn.close()
        return [_deserialize_subagent(row) for row in rows]

    @staticmethod
    def insert(subagent: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO subagents (id, parent_agent, task_id, task, context, expected_output_schema, status, lifecycle, result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                subagent["id"],
                subagent["parent_agent"],
                subagent["task_id"],
                subagent["task"],
                subagent.get("context", ""),
                json.dumps(subagent.get("expected_output_schema", {}), ensure_ascii=False),
                subagent.get("status", "running"),
                subagent.get("lifecycle", "destroy_after_return"),
                json.dumps(subagent.get("result"), ensure_ascii=False) if subagent.get("result") else None,
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def update_result(subagent_id: str, result: dict, status: str = "completed"):
        conn = get_connection()
        conn.execute(
            "UPDATE subagents SET result = ?, status = ?, lifecycle = 'destroyed' WHERE id = ?",
            (json.dumps(result, ensure_ascii=False), status, subagent_id),
        )
        conn.commit()
        conn.close()


class OutputRepository:
    @staticmethod
    def get_by_id(output_id: str) -> dict | None:
        conn = get_connection()
        row = conn.execute("SELECT * FROM outputs WHERE id = ?", (output_id,)).fetchone()
        conn.close()
        return _deserialize_output(row) if row else None

    @staticmethod
    def insert(output: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO outputs (id, output_type, title, content, run_id, task_id, agent_id, format, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                output["id"],
                output["output_type"],
                output["title"],
                output["content"],
                output.get("run_id"),
                output.get("task_id"),
                output.get("agent_id"),
                output.get("format", "markdown"),
                output["created_at"],
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM outputs WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        conn.close()
        return [_deserialize_output(row) for row in rows]


class RunRepository:
    @staticmethod
    def insert(run: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO runs (
                id, research_goal, status, current_step, task_ids, agent_assignments,
                created_at, updated_at, started_at, completed_at, cancel_requested_at,
                cancel_reason, total_cost_usd, total_tokens, total_llm_calls, last_event_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["id"],
                run["research_goal"],
                run.get("status", "created"),
                run.get("current_step", ""),
                json.dumps(run.get("task_ids", []), ensure_ascii=False),
                json.dumps(run.get("agent_assignments", {}), ensure_ascii=False),
                run["created_at"],
                run["updated_at"],
                run.get("started_at"),
                run.get("completed_at"),
                run.get("cancel_requested_at"),
                run.get("cancel_reason"),
                run.get("total_cost_usd", 0),
                run.get("total_tokens", 0),
                run.get("total_llm_calls", 0),
                run.get("last_event_id"),
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_id(run_id: str) -> Optional[dict]:
        conn = get_connection()
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()
        return _deserialize_run(row) if row else None

    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
        conn.close()
        return [_deserialize_run(row) for row in rows]

    @staticmethod
    def update_status(run_id: str, status: str, **kwargs):
        conn = get_connection()
        updates = ["status = ?", "updated_at = ?"]
        params: list = [status, datetime.now().isoformat()]
        for key, value in kwargs.items():
            if key in ("task_ids", "agent_assignments"):
                updates.append(f"{key} = ?")
                params.append(json.dumps(value, ensure_ascii=False))
            elif key in (
                "current_step",
                "started_at",
                "completed_at",
                "cancel_requested_at",
                "cancel_reason",
                "last_event_id",
            ):
                updates.append(f"{key} = ?")
                params.append(value)
            elif key in ("total_cost_usd", "total_tokens", "total_llm_calls"):
                updates.append(f"{key} = ?")
                params.append(value)
        params.append(run_id)
        conn.execute(f"UPDATE runs SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        conn.close()

    @staticmethod
    def increment_usage(run_id: str, cost_usd: float, tokens: int):
        conn = get_connection()
        conn.execute(
            """
            UPDATE runs
            SET total_cost_usd = COALESCE(total_cost_usd, 0) + ?,
                total_tokens = COALESCE(total_tokens, 0) + ?,
                total_llm_calls = COALESCE(total_llm_calls, 0) + 1,
                updated_at = ?
            WHERE id = ?
            """,
            (cost_usd, tokens, datetime.now().isoformat(), run_id),
        )
        conn.commit()
        conn.close()


class RunEventRepository:
    @staticmethod
    def insert(event: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO run_events (
                id, run_id, task_id, agent_id, subagent_id, event_type, phase,
                title, message, payload, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["id"],
                event["run_id"],
                event.get("task_id"),
                event.get("agent_id"),
                event.get("subagent_id"),
                event["event_type"],
                event["phase"],
                event["title"],
                event.get("message", ""),
                json.dumps(event.get("payload", {}), ensure_ascii=False),
                event["created_at"],
            ),
        )
        conn.execute("UPDATE runs SET last_event_id = ?, updated_at = ? WHERE id = ?", (event["id"], event["created_at"], event["run_id"]))
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str, limit: int = 100, after_id: str | None = None, phase: str | None = None, task_id: str | None = None) -> list[dict]:
        conn = get_connection()
        clauses = ["run_id = ?"]
        params: list = [run_id]
        if after_id:
            after = conn.execute("SELECT created_at FROM run_events WHERE id = ?", (after_id,)).fetchone()
            if after:
                clauses.append("created_at > ?")
                params.append(after["created_at"])
        if phase:
            clauses.append("phase = ?")
            params.append(phase)
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM run_events WHERE {' AND '.join(clauses)} ORDER BY created_at ASC LIMIT ?",
            params,
        ).fetchall()
        conn.close()
        return [_deserialize_run_event(row) for row in rows]

    @staticmethod
    def get_latest(run_id: str) -> dict | None:
        conn = get_connection()
        row = conn.execute("SELECT * FROM run_events WHERE run_id = ? ORDER BY created_at DESC LIMIT 1", (run_id,)).fetchone()
        conn.close()
        return _deserialize_run_event(row) if row else None


class LLMUsageRepository:
    @staticmethod
    def insert(item: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO llm_usage (
                id, run_id, task_id, agent_id, role, provider, model, prompt_tokens,
                completion_tokens, total_tokens, cost_usd, latency_ms, success, error, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item.get("run_id"),
                item.get("task_id"),
                item.get("agent_id"),
                item["role"],
                item["provider"],
                item["model"],
                item.get("prompt_tokens", 0),
                item.get("completion_tokens", 0),
                item.get("total_tokens", 0),
                item.get("cost_usd", 0),
                item.get("latency_ms", 0),
                int(item.get("success", True)),
                item.get("error"),
                item["created_at"],
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM llm_usage WHERE run_id = ? ORDER BY created_at ASC", (run_id,)).fetchall()
        conn.close()
        return [_deserialize_usage(row) for row in rows]

    @staticmethod
    def get_summary(run_id: str) -> dict:
        items = LLMUsageRepository.get_by_run(run_id)
        total_latency = sum(item["latency_ms"] for item in items)
        return {
            "total_cost_usd": sum(item["cost_usd"] for item in items),
            "total_tokens": sum(item["total_tokens"] for item in items),
            "total_llm_calls": len(items),
            "failed_llm_calls": len([item for item in items if not item["success"]]),
            "avg_latency_ms": int(total_latency / len(items)) if items else 0,
        }


def _json_loads(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _deserialize_agent(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "type": row["type"],
        "description": row["description"],
        "skills": _json_loads(row["skills"], {}),
        "status": row["status"],
        "current_load": row["current_load"],
        "max_load": row["max_load"],
        "current_tasks": _json_loads(row["current_tasks"], []),
        "preferred_task_types": _json_loads(row["preferred_task_types"], []),
        "tools": _json_loads(row["tools"], []),
        "can_create_subagents": bool(row["can_create_subagents"]),
        "max_subagents": row["max_subagents"],
    }


def _deserialize_task(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "task_type": row["task_type"],
        "required_skills": _json_loads(row["required_skills"], {}),
        "priority": row["priority"],
        "complexity": row["complexity"],
        "decomposability": row["decomposability"],
        "status": row["status"],
        "owner_agent": row["owner_agent"],
        "collaborator_agents": _json_loads(row["collaborator_agents"], []),
        "subtasks": _json_loads(row["subtasks"], []),
        "outputs": _json_loads(row["outputs"], []),
        "review_result": _json_loads(row["review_result"], None) if row["review_result"] else None,
        "review_feedback": row["review_feedback"],
        "run_id": row["run_id"],
        "assignment_info": _json_loads(row["assignment_info"] if "assignment_info" in keys else None, {}),
        "subagent_triggered": bool(row["subagent_triggered"]) if "subagent_triggered" in keys else False,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _deserialize_subagent(row) -> dict:
    return {
        "id": row["id"],
        "parent_agent": row["parent_agent"],
        "task_id": row["task_id"],
        "task": row["task"],
        "context": row["context"],
        "expected_output_schema": _json_loads(row["expected_output_schema"], {}),
        "status": row["status"],
        "lifecycle": row["lifecycle"],
        "result": _json_loads(row["result"], None) if row["result"] else None,
    }


def _deserialize_output(row) -> dict:
    return {
        "id": row["id"],
        "output_type": row["output_type"],
        "title": row["title"],
        "content": row["content"],
        "run_id": row["run_id"],
        "task_id": row["task_id"],
        "agent_id": row["agent_id"],
        "format": row["format"],
        "created_at": row["created_at"],
    }


def _deserialize_run(row) -> dict:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "research_goal": row["research_goal"],
        "status": row["status"],
        "current_step": row["current_step"],
        "task_ids": _json_loads(row["task_ids"], []),
        "agent_assignments": _json_loads(row["agent_assignments"], {}),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"] if "started_at" in keys else None,
        "completed_at": row["completed_at"],
        "cancel_requested_at": row["cancel_requested_at"] if "cancel_requested_at" in keys else None,
        "cancel_reason": row["cancel_reason"] if "cancel_reason" in keys else None,
        "total_cost_usd": row["total_cost_usd"] if "total_cost_usd" in keys else 0,
        "total_tokens": row["total_tokens"] if "total_tokens" in keys else 0,
        "total_llm_calls": row["total_llm_calls"] if "total_llm_calls" in keys else 0,
        "last_event_id": row["last_event_id"] if "last_event_id" in keys else None,
    }


def _deserialize_run_event(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "task_id": row["task_id"],
        "agent_id": row["agent_id"],
        "subagent_id": row["subagent_id"],
        "event_type": row["event_type"],
        "phase": row["phase"],
        "title": row["title"],
        "message": row["message"],
        "payload": _json_loads(row["payload"], {}),
        "created_at": row["created_at"],
    }


def _deserialize_usage(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "task_id": row["task_id"],
        "agent_id": row["agent_id"],
        "role": row["role"],
        "provider": row["provider"],
        "model": row["model"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "total_tokens": row["total_tokens"],
        "cost_usd": row["cost_usd"],
        "latency_ms": row["latency_ms"],
        "success": bool(row["success"]),
        "error": row["error"],
        "created_at": row["created_at"],
    }
