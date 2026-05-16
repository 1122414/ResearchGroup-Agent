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
                review_result, review_feedback, run_id, assignment_info, subagent_triggered,
                blocked_reason, parallelizable, is_critical_path, attempt_count, last_checkpoint,
                revision_of_task_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                task.get("blocked_reason"),
                int(task.get("parallelizable", True)),
                int(task.get("is_critical_path", False)),
                task.get("attempt_count", 0),
                task.get("last_checkpoint"),
                task.get("revision_of_task_id"),
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
            elif key in ("subagent_triggered", "parallelizable", "is_critical_path"):
                updates.append(f"{key} = ?")
                params.append(int(value))
            elif key == "review_result":
                updates.append(f"{key} = ?")
                params.append(json.dumps(value, ensure_ascii=False) if value else None)
            elif key in ("owner_agent", "review_feedback", "run_id", "blocked_reason", "last_checkpoint", "revision_of_task_id"):
                updates.append(f"{key} = ?")
                params.append(value)
            elif key == "attempt_count":
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
                id, display_name, artifact_dir, research_goal, status, current_step, task_ids, agent_assignments,
                created_at, updated_at, started_at, completed_at, cancel_requested_at,
                cancel_reason, total_cost_usd, total_tokens, total_llm_calls, last_event_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["id"],
                run.get("display_name"),
                run.get("artifact_dir"),
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
    def count_created_on(day_key: str) -> int:
        conn = get_connection()
        row = conn.execute("SELECT COUNT(*) AS total FROM runs WHERE created_at LIKE ?", (f"{day_key}%",)).fetchone()
        conn.close()
        return int(row["total"] if row else 0)

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
                "display_name",
                "artifact_dir",
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

    @staticmethod
    def delete(run_id: str):
        conn = get_connection()
        task_rows = conn.execute("SELECT id FROM tasks WHERE run_id = ?", (run_id,)).fetchall()
        task_ids = [row["id"] for row in task_rows]
        for task_id in task_ids:
            conn.execute("DELETE FROM subagents WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM task_dependencies WHERE task_id = ? OR depends_on_task_id = ?", (task_id, task_id))
            conn.execute("DELETE FROM task_attempts WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM recovery_actions WHERE task_id = ?", (task_id,))
        conn.execute("DELETE FROM outputs WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM run_events WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM llm_usage WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM memory_records WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM evidence_claims WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM evidence_sources WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM review_decisions WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM approval_requests WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM research_briefs WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM research_hypotheses WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM research_claims WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM research_decisions WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM research_uncertainties WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM tasks WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
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


class AgentSkillRepository:
    @staticmethod
    def insert(skill: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO agent_skills (
                id, agent_id, title, description, content, status, confidence,
                source_run_id, source_task_id, tags, file_path, usage_count,
                failure_count, created_at, updated_at, last_used_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                skill["id"],
                skill["agent_id"],
                skill["title"],
                skill.get("description", ""),
                skill["content"],
                skill.get("status", "draft"),
                skill.get("confidence", 0.0),
                skill.get("source_run_id"),
                skill.get("source_task_id"),
                json.dumps(skill.get("tags", []), ensure_ascii=False),
                skill["file_path"],
                skill.get("usage_count", 0),
                skill.get("failure_count", 0),
                skill["created_at"],
                skill["updated_at"],
                skill.get("last_used_at"),
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_id(skill_id: str) -> dict | None:
        conn = get_connection()
        row = conn.execute("SELECT * FROM agent_skills WHERE id = ?", (skill_id,)).fetchone()
        conn.close()
        return _deserialize_agent_skill(row) if row else None

    @staticmethod
    def get_all(agent_id: str | None = None, status: str | None = None, q: str | None = None) -> list[dict]:
        conn = get_connection()
        clauses: list[str] = []
        params: list = []
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if q:
            clauses.append("(title LIKE ? OR description LIKE ? OR tags LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM agent_skills {where} ORDER BY COALESCE(last_used_at, updated_at) DESC, updated_at DESC",
            params,
        ).fetchall()
        conn.close()
        return [_deserialize_agent_skill(row) for row in rows]

    @staticmethod
    def update(skill_id: str, updates: dict):
        if not updates:
            return
        conn = get_connection()
        assignments: list[str] = []
        params: list = []
        for key, value in updates.items():
            if key == "tags":
                assignments.append("tags = ?")
                params.append(json.dumps(value, ensure_ascii=False))
            elif key in {
                "title",
                "description",
                "content",
                "status",
                "confidence",
                "file_path",
                "usage_count",
                "failure_count",
                "last_used_at",
                "updated_at",
            }:
                assignments.append(f"{key} = ?")
                params.append(value)
        if assignments:
            params.append(skill_id)
            conn.execute(f"UPDATE agent_skills SET {', '.join(assignments)} WHERE id = ?", params)
            conn.commit()
        conn.close()

    @staticmethod
    def delete(skill_id: str):
        conn = get_connection()
        conn.execute("DELETE FROM agent_skills WHERE id = ?", (skill_id,))
        conn.commit()
        conn.close()


class ExperimentPlanRepository:
    @staticmethod
    def insert(plan: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO experiment_plans (
                id, run_id, task_id, agent_id, title, objective, workspace_dir,
                files, commands, env_vars, risk_level, risk_reasons, status,
                result, artifacts, created_at, updated_at, approved_at, approved_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan["id"],
                plan.get("run_id"),
                plan.get("task_id"),
                plan.get("agent_id", "experiment_agent"),
                plan["title"],
                plan.get("objective", ""),
                plan["workspace_dir"],
                json.dumps(plan.get("files", []), ensure_ascii=False),
                json.dumps(plan.get("commands", []), ensure_ascii=False),
                json.dumps(plan.get("env_vars", {}), ensure_ascii=False),
                plan.get("risk_level", "needs_review"),
                json.dumps(plan.get("risk_reasons", []), ensure_ascii=False),
                plan.get("status", "draft"),
                json.dumps(plan.get("result"), ensure_ascii=False) if plan.get("result") else None,
                json.dumps(plan.get("artifacts", []), ensure_ascii=False),
                plan["created_at"],
                plan["updated_at"],
                plan.get("approved_at"),
                plan.get("approved_by"),
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_id(plan_id: str) -> dict | None:
        conn = get_connection()
        row = conn.execute("SELECT * FROM experiment_plans WHERE id = ?", (plan_id,)).fetchone()
        conn.close()
        return _deserialize_experiment_plan(row) if row else None

    @staticmethod
    def get_all(run_id: str | None = None, task_id: str | None = None, status: str | None = None) -> list[dict]:
        conn = get_connection()
        clauses: list[str] = []
        params: list = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(f"SELECT * FROM experiment_plans {where} ORDER BY updated_at DESC", params).fetchall()
        conn.close()
        return [_deserialize_experiment_plan(row) for row in rows]

    @staticmethod
    def update(plan_id: str, updates: dict):
        if not updates:
            return
        conn = get_connection()
        assignments: list[str] = []
        params: list = []
        json_fields = {"files", "commands", "env_vars", "risk_reasons", "result", "artifacts"}
        allowed_fields = {
            "run_id",
            "task_id",
            "agent_id",
            "title",
            "objective",
            "workspace_dir",
            "risk_level",
            "status",
            "updated_at",
            "approved_at",
            "approved_by",
        }
        for key, value in updates.items():
            if key in json_fields:
                assignments.append(f"{key} = ?")
                params.append(json.dumps(value, ensure_ascii=False) if value is not None else None)
            elif key in allowed_fields:
                assignments.append(f"{key} = ?")
                params.append(value)
        if assignments:
            params.append(plan_id)
            conn.execute(f"UPDATE experiment_plans SET {', '.join(assignments)} WHERE id = ?", params)
            conn.commit()
        conn.close()


class TaskDependencyRepository:
    @staticmethod
    def replace_for_task(task_id: str, dependencies: list[str]):
        conn = get_connection()
        conn.execute("DELETE FROM task_dependencies WHERE task_id = ?", (task_id,))
        for dependency in dependencies:
            conn.execute(
                "INSERT INTO task_dependencies (task_id, depends_on_task_id, dependency_type) VALUES (?, ?, 'hard')",
                (task_id, dependency),
            )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT d.* FROM task_dependencies d
            JOIN tasks t ON t.id = d.task_id
            WHERE t.run_id = ?
            ORDER BY d.task_id, d.depends_on_task_id
            """,
            (run_id,),
        ).fetchall()
        conn.close()
        return [
            {
                "task_id": row["task_id"],
                "depends_on_task_id": row["depends_on_task_id"],
                "dependency_type": row["dependency_type"],
            }
            for row in rows
        ]

    @staticmethod
    def get_for_task(task_id: str) -> list[str]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT depends_on_task_id FROM task_dependencies WHERE task_id = ? ORDER BY depends_on_task_id",
            (task_id,),
        ).fetchall()
        conn.close()
        return [row["depends_on_task_id"] for row in rows]


class TaskAttemptRepository:
    @staticmethod
    def insert(attempt: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO task_attempts (
                id, run_id, task_id, attempt_number, status, failure_type,
                failure_message, checkpoint, started_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt["id"],
                attempt["run_id"],
                attempt["task_id"],
                attempt.get("attempt_number", 1),
                attempt.get("status", "running"),
                attempt.get("failure_type"),
                attempt.get("failure_message"),
                attempt.get("checkpoint"),
                attempt["started_at"],
                attempt.get("completed_at"),
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def update(attempt_id: str, **updates):
        conn = get_connection()
        assignments: list[str] = []
        params: list = []
        for key in ("status", "failure_type", "failure_message", "checkpoint", "completed_at"):
            if key in updates:
                assignments.append(f"{key} = ?")
                params.append(updates[key])
        if assignments:
            params.append(attempt_id)
            conn.execute(f"UPDATE task_attempts SET {', '.join(assignments)} WHERE id = ?", params)
            conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM task_attempts WHERE run_id = ? ORDER BY started_at", (run_id,)).fetchall()
        conn.close()
        return [_deserialize_task_attempt(row) for row in rows]

    @staticmethod
    def get_for_task(task_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM task_attempts WHERE task_id = ? ORDER BY started_at", (task_id,)).fetchall()
        conn.close()
        return [_deserialize_task_attempt(row) for row in rows]


class RecoveryActionRepository:
    @staticmethod
    def insert(action: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO recovery_actions (id, run_id, task_id, action_type, status, reason, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action["id"],
                action["run_id"],
                action["task_id"],
                action["action_type"],
                action.get("status", "requested"),
                action.get("reason", ""),
                json.dumps(action.get("payload", {}), ensure_ascii=False),
                action["created_at"],
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM recovery_actions WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        conn.close()
        return [_deserialize_recovery_action(row) for row in rows]


class MemoryRecordRepository:
    @staticmethod
    def insert(record: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO memory_records (
                id, run_id, agent_id, scope, category, summary, payload,
                source_task_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["run_id"],
                record.get("agent_id"),
                record["scope"],
                record["category"],
                record["summary"],
                json.dumps(record.get("payload", {}), ensure_ascii=False),
                record.get("source_task_id"),
                record["created_at"],
                record["updated_at"],
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM memory_records WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        conn.close()
        return [_deserialize_memory_record(row) for row in rows]

    @staticmethod
    def search(run_id: str, query: str, agent_id: str | None = None) -> list[dict]:
        conn = get_connection()
        clauses = ["run_id = ?", "(summary LIKE ? OR payload LIKE ?)"]
        params: list = [run_id, f"%{query}%", f"%{query}%"]
        if agent_id:
            clauses.append("(agent_id = ? OR scope = 'project')")
            params.append(agent_id)
        rows = conn.execute(
            f"SELECT * FROM memory_records WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC",
            params,
        ).fetchall()
        conn.close()
        return [_deserialize_memory_record(row) for row in rows]


class EvidenceRepository:
    @staticmethod
    def upsert_source(source: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT OR REPLACE INTO evidence_sources (
                id, run_id, task_id, title, authors, year, venue, doi,
                url, source_type, metadata, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source["id"],
                source["run_id"],
                source.get("task_id"),
                source["title"],
                source.get("authors", ""),
                source.get("year"),
                source.get("venue", ""),
                source.get("doi"),
                source.get("url"),
                source.get("source_type", "paper"),
                json.dumps(source.get("metadata", {}), ensure_ascii=False),
                source["created_at"],
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def insert_claim(claim: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO evidence_claims (
                id, run_id, task_id, source_id, claim, method, relation_type, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim["id"],
                claim["run_id"],
                claim.get("task_id"),
                claim["source_id"],
                claim["claim"],
                claim.get("method", ""),
                claim.get("relation_type", "supports"),
                claim["created_at"],
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> dict:
        conn = get_connection()
        sources = conn.execute("SELECT * FROM evidence_sources WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        claims = conn.execute("SELECT * FROM evidence_claims WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        conn.close()
        return {
            "sources": [_deserialize_evidence_source(row) for row in sources],
            "claims": [_deserialize_evidence_claim(row) for row in claims],
        }


class ReviewDecisionRepository:
    @staticmethod
    def insert(decision: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO review_decisions (
                id, run_id, task_id, rubric, scores, approved, feedback,
                requires_revision, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision["id"],
                decision["run_id"],
                decision["task_id"],
                json.dumps(decision.get("rubric", {}), ensure_ascii=False),
                json.dumps(decision.get("scores", {}), ensure_ascii=False),
                int(decision.get("approved", True)),
                decision.get("feedback", ""),
                int(decision.get("requires_revision", False)),
                decision["created_at"],
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM review_decisions WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        conn.close()
        return [_deserialize_review_decision(row) for row in rows]


class ApprovalRequestRepository:
    @staticmethod
    def insert(request: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO approval_requests (
                id, run_id, task_id, request_type, status, title, message,
                payload, created_at, resolved_at, resolved_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request["id"],
                request["run_id"],
                request.get("task_id"),
                request["request_type"],
                request.get("status", "pending"),
                request["title"],
                request.get("message", ""),
                json.dumps(request.get("payload", {}), ensure_ascii=False),
                request["created_at"],
                request.get("resolved_at"),
                request.get("resolved_by"),
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def update(request_id: str, **updates):
        conn = get_connection()
        assignments: list[str] = []
        params: list = []
        for key in ("status", "resolved_at", "resolved_by"):
            if key in updates:
                assignments.append(f"{key} = ?")
                params.append(updates[key])
        if assignments:
            params.append(request_id)
            conn.execute(f"UPDATE approval_requests SET {', '.join(assignments)} WHERE id = ?", params)
            conn.commit()
        conn.close()

    @staticmethod
    def get_by_id(request_id: str) -> dict | None:
        conn = get_connection()
        row = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
        conn.close()
        return _deserialize_approval_request(row) if row else None

    @staticmethod
    def get_by_run(run_id: str, status: str | None = None) -> list[dict]:
        conn = get_connection()
        if status:
            rows = conn.execute(
                "SELECT * FROM approval_requests WHERE run_id = ? AND status = ? ORDER BY created_at",
                (run_id, status),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM approval_requests WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        conn.close()
        return [_deserialize_approval_request(row) for row in rows]

    @staticmethod
    def find_pending(run_id: str, request_type: str, task_id: str | None = None) -> dict | None:
        conn = get_connection()
        if task_id:
            row = conn.execute(
                """
                SELECT * FROM approval_requests
                WHERE run_id = ? AND request_type = ? AND task_id = ? AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
                """,
                (run_id, request_type, task_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM approval_requests
                WHERE run_id = ? AND request_type = ? AND task_id IS NULL AND status = 'pending'
                ORDER BY created_at DESC LIMIT 1
                """,
                (run_id, request_type),
            ).fetchone()
        conn.close()
        return _deserialize_approval_request(row) if row else None


class ResearchBriefRepository:
    @staticmethod
    def insert(brief: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO research_briefs (
                id, run_id, research_question, objective, scope, success_criteria,
                constraints, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                brief["id"],
                brief["run_id"],
                brief["research_question"],
                brief["objective"],
                brief.get("scope", ""),
                json.dumps(brief.get("success_criteria", []), ensure_ascii=False),
                json.dumps(brief.get("constraints", []), ensure_ascii=False),
                brief.get("status", "active"),
                brief["created_at"],
                brief["updated_at"],
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> dict | None:
        conn = get_connection()
        row = conn.execute("SELECT * FROM research_briefs WHERE run_id = ?", (run_id,)).fetchone()
        conn.close()
        return _deserialize_research_brief(row) if row else None


class ResearchHypothesisRepository:
    @staticmethod
    def insert(hypothesis: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO research_hypotheses (
                id, run_id, statement, rationale, status, confidence, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hypothesis["id"],
                hypothesis["run_id"],
                hypothesis["statement"],
                hypothesis.get("rationale", ""),
                hypothesis.get("status", "proposed"),
                hypothesis.get("confidence", 0),
                hypothesis["created_at"],
                hypothesis["updated_at"],
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM research_hypotheses WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        conn.close()
        return [_deserialize_research_hypothesis(row) for row in rows]


class ResearchClaimRepository:
    @staticmethod
    def insert(claim: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO research_claims (
                id, run_id, hypothesis_id, statement, status, evidence_ids,
                confidence, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                claim["id"],
                claim["run_id"],
                claim.get("hypothesis_id"),
                claim["statement"],
                claim.get("status", "draft"),
                json.dumps(claim.get("evidence_ids", []), ensure_ascii=False),
                claim.get("confidence", 0),
                claim["created_at"],
                claim["updated_at"],
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM research_claims WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        conn.close()
        return [_deserialize_research_claim(row) for row in rows]


class ResearchDecisionRepository:
    @staticmethod
    def insert(decision: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO research_decisions (id, run_id, decision, rationale, impact, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                decision["id"],
                decision["run_id"],
                decision["decision"],
                decision.get("rationale", ""),
                decision.get("impact", ""),
                decision["created_at"],
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM research_decisions WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        conn.close()
        return [_deserialize_research_decision(row) for row in rows]


class ResearchUncertaintyRepository:
    @staticmethod
    def insert(uncertainty: dict):
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO research_uncertainties (
                id, run_id, description, category, severity, status, created_at, resolved_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uncertainty["id"],
                uncertainty["run_id"],
                uncertainty["description"],
                uncertainty.get("category", "research_question"),
                uncertainty.get("severity", "medium"),
                uncertainty.get("status", "open"),
                uncertainty["created_at"],
                uncertainty.get("resolved_at"),
            ),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_by_run(run_id: str) -> list[dict]:
        conn = get_connection()
        rows = conn.execute("SELECT * FROM research_uncertainties WHERE run_id = ? ORDER BY created_at", (run_id,)).fetchall()
        conn.close()
        return [_deserialize_research_uncertainty(row) for row in rows]


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
    keys = set(row.keys())
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
        "blocked_reason": row["blocked_reason"] if "blocked_reason" in keys else None,
        "parallelizable": bool(row["parallelizable"]) if "parallelizable" in keys else True,
        "is_critical_path": bool(row["is_critical_path"]) if "is_critical_path" in keys else False,
        "attempt_count": row["attempt_count"] if "attempt_count" in keys else 0,
        "last_checkpoint": row["last_checkpoint"] if "last_checkpoint" in keys else None,
        "revision_of_task_id": row["revision_of_task_id"] if "revision_of_task_id" in keys else None,
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
        "display_name": row["display_name"] if "display_name" in keys else None,
        "artifact_dir": row["artifact_dir"] if "artifact_dir" in keys else None,
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


def _deserialize_agent_skill(row) -> dict:
    return {
        "id": row["id"],
        "agent_id": row["agent_id"],
        "title": row["title"],
        "description": row["description"],
        "content": row["content"],
        "status": row["status"],
        "confidence": row["confidence"],
        "source_run_id": row["source_run_id"],
        "source_task_id": row["source_task_id"],
        "tags": _json_loads(row["tags"], []),
        "file_path": row["file_path"],
        "usage_count": row["usage_count"],
        "failure_count": row["failure_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_used_at": row["last_used_at"],
    }


def _deserialize_experiment_plan(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "task_id": row["task_id"],
        "agent_id": row["agent_id"],
        "title": row["title"],
        "objective": row["objective"],
        "workspace_dir": row["workspace_dir"],
        "files": _json_loads(row["files"], []),
        "commands": _json_loads(row["commands"], []),
        "env_vars": _json_loads(row["env_vars"], {}),
        "risk_level": row["risk_level"],
        "risk_reasons": _json_loads(row["risk_reasons"], []),
        "status": row["status"],
        "result": _json_loads(row["result"], None) if row["result"] else None,
        "artifacts": _json_loads(row["artifacts"], []),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "approved_at": row["approved_at"],
        "approved_by": row["approved_by"],
    }


def _deserialize_task_attempt(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "task_id": row["task_id"],
        "attempt_number": row["attempt_number"],
        "status": row["status"],
        "failure_type": row["failure_type"],
        "failure_message": row["failure_message"],
        "checkpoint": row["checkpoint"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }


def _deserialize_recovery_action(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "task_id": row["task_id"],
        "action_type": row["action_type"],
        "status": row["status"],
        "reason": row["reason"],
        "payload": _json_loads(row["payload"], {}),
        "created_at": row["created_at"],
    }


def _deserialize_memory_record(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "agent_id": row["agent_id"],
        "scope": row["scope"],
        "category": row["category"],
        "summary": row["summary"],
        "payload": _json_loads(row["payload"], {}),
        "source_task_id": row["source_task_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _deserialize_evidence_source(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "task_id": row["task_id"],
        "title": row["title"],
        "authors": row["authors"],
        "year": row["year"],
        "venue": row["venue"],
        "doi": row["doi"],
        "url": row["url"],
        "source_type": row["source_type"],
        "metadata": _json_loads(row["metadata"], {}),
        "created_at": row["created_at"],
    }


def _deserialize_evidence_claim(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "task_id": row["task_id"],
        "source_id": row["source_id"],
        "claim": row["claim"],
        "method": row["method"],
        "relation_type": row["relation_type"],
        "created_at": row["created_at"],
    }


def _deserialize_review_decision(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "task_id": row["task_id"],
        "rubric": _json_loads(row["rubric"], {}),
        "scores": _json_loads(row["scores"], {}),
        "approved": bool(row["approved"]),
        "feedback": row["feedback"],
        "requires_revision": bool(row["requires_revision"]),
        "created_at": row["created_at"],
    }


def _deserialize_approval_request(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "task_id": row["task_id"],
        "request_type": row["request_type"],
        "status": row["status"],
        "title": row["title"],
        "message": row["message"],
        "payload": _json_loads(row["payload"], {}),
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
        "resolved_by": row["resolved_by"],
    }


def _deserialize_research_brief(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "research_question": row["research_question"],
        "objective": row["objective"],
        "scope": row["scope"],
        "success_criteria": _json_loads(row["success_criteria"], []),
        "constraints": _json_loads(row["constraints"], []),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _deserialize_research_hypothesis(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "statement": row["statement"],
        "rationale": row["rationale"],
        "status": row["status"],
        "confidence": row["confidence"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _deserialize_research_claim(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "hypothesis_id": row["hypothesis_id"],
        "statement": row["statement"],
        "status": row["status"],
        "evidence_ids": _json_loads(row["evidence_ids"], []),
        "confidence": row["confidence"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _deserialize_research_decision(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "decision": row["decision"],
        "rationale": row["rationale"],
        "impact": row["impact"],
        "created_at": row["created_at"],
    }


def _deserialize_research_uncertainty(row) -> dict:
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "description": row["description"],
        "category": row["category"],
        "severity": row["severity"],
        "status": row["status"],
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
    }
