import json
from typing import Optional
from .db import get_connection


class AgentRepository:
    @staticmethod
    def get_all() -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM agents").fetchall()
        conn.close()
        return [_deserialize_agent(r) for r in rows]

    @staticmethod
    def get_by_id(agent_id: str) -> Optional[dict]:
        conn = get_connection()
        row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        conn.close()
        return _deserialize_agent(row) if row else None

    @staticmethod
    def upsert(agent: dict):
        conn = get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO agents (id, name, type, description, skills, status, current_load, max_load,
                current_tasks, preferred_task_types, tools, can_create_subagents, max_subagents)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent["id"], agent["name"], agent["type"], agent["description"],
            json.dumps(agent["skills"], ensure_ascii=False),
            agent.get("status", "idle"), agent.get("current_load", 0.0),
            agent.get("max_load", 1.0), json.dumps(agent.get("current_tasks", [])),
            json.dumps(agent.get("preferred_task_types", [])),
            json.dumps(agent.get("tools", [])),
            int(agent.get("can_create_subagents", True)),
            agent.get("max_subagents", 0)
        ))
        conn.commit()
        conn.close()

    @staticmethod
    def update_status(agent_id: str, status: str, current_load: float = 0.0):
        conn = get_connection()
        conn.execute("UPDATE agents SET status = ?, current_load = ? WHERE id = ?", (status, current_load, agent_id))
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
        return [_deserialize_task(r) for r in rows]

    @staticmethod
    def get_by_id(task_id: str) -> Optional[dict]:
        conn = get_connection()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        return _deserialize_task(row) if row else None

    @staticmethod
    def insert(task: dict):
        conn = get_connection()
        conn.execute("""
            INSERT INTO tasks (id, title, description, task_type, required_skills, priority, complexity,
                decomposability, status, owner_agent, collaborator_agents, subtasks, outputs,
                review_result, review_feedback, run_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task["id"], task["title"], task.get("description", ""), task["task_type"],
            json.dumps(task["required_skills"], ensure_ascii=False),
            task.get("priority", 5), task.get("complexity", 5), task.get("decomposability", 5),
            task.get("status", "pending"), task.get("owner_agent"),
            json.dumps(task.get("collaborator_agents", [])),
            json.dumps(task.get("subtasks", [])),
            json.dumps(task.get("outputs", [])),
            json.dumps(task.get("review_result")) if task.get("review_result") else None,
            task.get("review_feedback"),
            task.get("run_id"), task["created_at"], task["updated_at"]
        ))
        conn.commit()
        conn.close()

    @staticmethod
    def update_status(task_id: str, status: str, **kwargs):
        conn = get_connection()
        updates = ["status = ?", "updated_at = ?"]
        params = [status, __import__("datetime").datetime.now().isoformat()]
        for key, value in kwargs.items():
            if key == "outputs" or key == "collaborator_agents" or key == "subtasks":
                updates.append(f"{key} = ?")
                params.append(json.dumps(value, ensure_ascii=False))
            elif key in ("review_result",):
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
        return [_deserialize_subagent(r) for r in rows]

    @staticmethod
    def insert(subagent: dict):
        conn = get_connection()
        conn.execute("""
            INSERT INTO subagents (id, parent_agent, task_id, task, context, expected_output_schema, status, lifecycle, result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            subagent["id"], subagent["parent_agent"], subagent["task_id"], subagent["task"],
            subagent.get("context", ""), json.dumps(subagent.get("expected_output_schema", {}), ensure_ascii=False),
            subagent.get("status", "running"), subagent.get("lifecycle", "destroy_after_return"),
            json.dumps(subagent.get("result"), ensure_ascii=False) if subagent.get("result") else None
        ))
        conn.commit()
        conn.close()

    @staticmethod
    def update_result(subagent_id: str, result: dict, status: str = "completed"):
        conn = get_connection()
        conn.execute("UPDATE subagents SET result = ?, status = ?, lifecycle = 'destroyed' WHERE id = ?",
                     (json.dumps(result, ensure_ascii=False), status, subagent_id))
        conn.commit()
        conn.close()


class OutputRepository:
    @staticmethod
    def insert(output: dict):
        conn = get_connection()
        conn.execute("""
            INSERT INTO outputs (id, output_type, title, content, run_id, task_id, agent_id, format, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            output["id"], output["output_type"], output["title"], output["content"],
            output.get("run_id"), output.get("task_id"), output.get("agent_id"),
            output.get("format", "markdown"), output["created_at"]
        ))
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM outputs WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        conn.close()
        return [_deserialize_output(r) for r in rows]

    @staticmethod
    def get_by_task(task_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM outputs WHERE task_id = ? ORDER BY created_at", (task_id,)).fetchall()
        conn.close()
        return [_deserialize_output(r) for r in rows]


class RunRepository:
    @staticmethod
    def insert(run: dict):
        conn = get_connection()
        conn.execute("""
            INSERT INTO runs (id, research_goal, status, current_step, task_ids, agent_assignments, created_at, updated_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run["id"], run["research_goal"], run.get("status", "created"), run.get("current_step", ""),
            json.dumps(run.get("task_ids", [])), json.dumps(run.get("agent_assignments", {}), ensure_ascii=False),
            run["created_at"], run["updated_at"], run.get("completed_at")
        ))
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
        return [_deserialize_run(r) for r in rows]

    @staticmethod
    def update_status(run_id: str, status: str, **kwargs):
        conn = get_connection()
        updates = ["status = ?", "updated_at = ?"]
        params = [status, __import__("datetime").datetime.now().isoformat()]
        for key, value in kwargs.items():
            if key in ("task_ids",):
                updates.append(f"{key} = ?")
                params.append(json.dumps(value))
            elif key in ("agent_assignments",):
                updates.append(f"{key} = ?")
                params.append(json.dumps(value, ensure_ascii=False))
            elif key in ("current_step", "completed_at"):
                updates.append(f"{key} = ?")
                params.append(value)
        params.append(run_id)
        conn.execute(f"UPDATE runs SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        conn.close()


def _deserialize_agent(row) -> dict:
    if not row:
        return None
    return {
        "id": row["id"], "name": row["name"], "type": row["type"],
        "description": row["description"],
        "skills": json.loads(row["skills"]),
        "status": row["status"], "current_load": row["current_load"],
        "max_load": row["max_load"],
        "current_tasks": json.loads(row["current_tasks"]),
        "preferred_task_types": json.loads(row["preferred_task_types"]),
        "tools": json.loads(row["tools"]),
        "can_create_subagents": bool(row["can_create_subagents"]),
        "max_subagents": row["max_subagents"],
    }


def _deserialize_task(row) -> dict:
    if not row:
        return None
    return {
        "id": row["id"], "title": row["title"], "description": row["description"],
        "task_type": row["task_type"],
        "required_skills": json.loads(row["required_skills"]),
        "priority": row["priority"], "complexity": row["complexity"],
        "decomposability": row["decomposability"],
        "status": row["status"], "owner_agent": row["owner_agent"],
        "collaborator_agents": json.loads(row["collaborator_agents"]),
        "subtasks": json.loads(row["subtasks"]),
        "outputs": json.loads(row["outputs"]),
        "review_result": json.loads(row["review_result"]) if row["review_result"] else None,
        "review_feedback": row["review_feedback"],
        "run_id": row["run_id"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _deserialize_subagent(row) -> dict:
    if not row:
        return None
    return {
        "id": row["id"], "parent_agent": row["parent_agent"], "task_id": row["task_id"],
        "task": row["task"], "context": row["context"],
        "expected_output_schema": json.loads(row["expected_output_schema"]),
        "status": row["status"], "lifecycle": row["lifecycle"],
        "result": json.loads(row["result"]) if row["result"] else None,
    }


def _deserialize_output(row) -> dict:
    if not row:
        return None
    return {
        "id": row["id"], "output_type": row["output_type"], "title": row["title"],
        "content": row["content"], "run_id": row["run_id"], "task_id": row["task_id"],
        "agent_id": row["agent_id"], "format": row["format"], "created_at": row["created_at"],
    }


def _deserialize_run(row) -> dict:
    if not row:
        return None
    return {
        "id": row["id"], "research_goal": row["research_goal"],
        "status": row["status"], "current_step": row["current_step"],
        "task_ids": json.loads(row["task_ids"]),
        "agent_assignments": json.loads(row["agent_assignments"]),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }
