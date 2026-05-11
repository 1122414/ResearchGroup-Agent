from ..core.config import settings
from ..core.logger import logger
from ..storage.repositories import AgentRepository, TaskRepository


class TaskScheduler:
    def assign_owner(self, task: dict, agents: list[dict]) -> tuple[str | None, dict]:
        logger.debug("[TaskScheduler] assign_owner | task_id=%s", task.get("id"))
        best_agent = None
        best_score = -1
        best_info = {}

        for agent in agents:
            skills = agent.get("skills", {})
            required = task.get("required_skills", {})
            skill_match = sum(
                skills.get(k, 1) * required.get(k, 1)
                for k in ["literature_review", "coding", "experiment", "data_analysis", "academic_writing", "mentoring"]
            )
            idle_factor = 1.0 - agent.get("current_load", 0.0)
            score = skill_match * settings.scheduler_skill_weight + idle_factor * settings.scheduler_idle_scale * settings.scheduler_idle_weight
            if score > best_score:
                best_score = score
                best_agent = agent
                top_skill = max(required.keys(), key=lambda k: required.get(k, 0) * skills.get(k, 0)) if required else ""
                best_info = {
                    "score": round(score, 2),
                    "skill_match": round(skill_match, 2),
                    "idle_factor": round(idle_factor, 2),
                    "primary_skill": top_skill,
                    "primary_skill_score": skills.get(top_skill, 0) if top_skill else 0,
                }

        owner_id = best_agent["id"] if best_agent else None
        logger.info("[TaskScheduler] assign_owner | task_id=%s | owner=%s | score=%.2f | skill_match=%.2f | primary_skill=%s",
                    task.get("id"), owner_id, best_info.get("score", 0), best_info.get("skill_match", 0), best_info.get("primary_skill", ""))
        return (owner_id, best_info)

    def assign_collaborators(self, task: dict, agents: list[dict], owner_id: str) -> list[str]:
        logger.debug("[TaskScheduler] assign_collaborators | task_id=%s | owner=%s", task.get("id"), owner_id)
        complexity = task.get("complexity", 5)
        owner = next((a for a in agents if a["id"] == owner_id), None)
        need_collab = (
            complexity >= settings.collab_complexity_threshold
            or (owner and owner.get("current_load", 0) >= settings.collab_load_threshold)
        )

        if not need_collab:
            return []

        candidates = []
        required = task.get("required_skills", {})
        for agent in agents:
            if agent["id"] == owner_id:
                continue
            if agent.get("current_load", 0) > 0.6:
                continue
            skills = agent.get("skills", {})
            for skill_name in ["literature_review", "coding", "experiment", "data_analysis", "academic_writing", "mentoring"]:
                if required.get(skill_name, 0) >= 3 and skills.get(skill_name, 1) >= 5:
                    candidates.append(agent["id"])
                    break

        collabs = candidates[:settings.collab_max_count]
        logger.info("[TaskScheduler] assign_collaborators | task_id=%s | collaborators=%s", task.get("id"), collabs)
        return collabs

    def assign_all(self, tasks: list[dict]) -> dict[str, list[str]]:
        logger.info("[TaskScheduler] assign_all started | task_count=%d", len(tasks))
        agents = AgentRepository.get_all()
        graduate_agents = [a for a in agents if a["type"] in ("researcher", "engineer", "experimenter", "analyst", "writer")]
        assignments = {}

        sorted_tasks = sorted(tasks, key=lambda t: t.get("priority", 5), reverse=True)

        for task in sorted_tasks:
            owner_id, assign_info = self.assign_owner(task, graduate_agents)
            collab_ids = self.assign_collaborators(task, graduate_agents, owner_id) if owner_id else []

            TaskRepository.update_status(
                task["id"],
                "assigned" if owner_id else "pending",
                owner_agent=owner_id,
                collaborator_agents=collab_ids,
                assignment_info=assign_info,
            )
            assignments[task["id"]] = {"owner": owner_id, "collaborators": collab_ids, "assignment_info": assign_info}

            if owner_id:
                current_tasks = json_loads_safe(AgentRepository.get_by_id(owner_id).get("current_tasks", []))
                current_tasks.append(task["id"])
                load = min(1.0, len(current_tasks) / 3.0)
                AgentRepository.update_status(owner_id, "working", load, current_tasks=current_tasks)

        logger.info("[TaskScheduler] assign_all completed | assignments=%d", len(assignments))
        return assignments


def json_loads_safe(value):
    import json
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


task_scheduler = TaskScheduler()
