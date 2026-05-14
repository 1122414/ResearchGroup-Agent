import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from ..core.config import settings
from ..models.agent_skill import AgentSkillCreate, AgentSkillUpdate
from ..storage.repositories import AgentRepository, AgentSkillRepository


ACTIVE_STATUSES = {"draft", "active", "disabled"}
VIRTUAL_SKILL_OWNERS = {
    "advisor": {"id": "advisor", "name": "导师 Agent", "type": "advisor", "scope": "advisor"},
    "undergrad_subagent_shared": {
        "id": "undergrad_subagent_shared",
        "name": "本科 SubAgent 共享 Skill",
        "type": "subagent_shared",
        "scope": "undergraduate_subagent",
    },
}


class AgentSkillService:
    def owners(self) -> list[dict]:
        graduate_agents = [
            {
                "id": agent["id"],
                "name": agent["name"],
                "type": agent["type"],
                "scope": "graduate_agent",
            }
            for agent in AgentRepository.get_all()
        ]
        return [VIRTUAL_SKILL_OWNERS["advisor"], *graduate_agents, VIRTUAL_SKILL_OWNERS["undergrad_subagent_shared"]]

    def list(self, agent_id: str | None = None, status: str | None = None, q: str | None = None) -> list[dict]:
        return AgentSkillRepository.get_all(agent_id=agent_id, status=status, q=q)

    def get(self, skill_id: str) -> dict:
        skill = AgentSkillRepository.get_by_id(skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill 不存在")
        return skill

    def create(self, data: AgentSkillCreate) -> dict:
        self._ensure_agent(data.agent_id)
        now = datetime.now().astimezone().isoformat()
        skill_id = f"skill_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
        skill = {
            "id": skill_id,
            "agent_id": data.agent_id,
            "title": data.title.strip(),
            "description": data.description.strip(),
            "content": data.content.strip(),
            "status": data.status,
            "confidence": data.confidence,
            "source_run_id": data.source_run_id,
            "source_task_id": data.source_task_id,
            "tags": data.tags,
            "file_path": "",
            "usage_count": 0,
            "failure_count": 0,
            "created_at": now,
            "updated_at": now,
            "last_used_at": None,
        }
        skill["file_path"] = str(self._skill_path(skill))
        self._write_skill_file(skill)
        AgentSkillRepository.insert(skill)
        return skill

    def update(self, skill_id: str, data: AgentSkillUpdate) -> dict:
        skill = self.get(skill_id)
        updates = data.model_dump(exclude_unset=True)
        if not updates:
            return skill

        old_path = Path(skill["file_path"])
        updated = {**skill, **updates, "updated_at": datetime.now().astimezone().isoformat()}
        if "title" in updates:
            updated["title"] = str(updated["title"]).strip()
        if "description" in updates:
            updated["description"] = str(updated["description"]).strip()
        if "content" in updates:
            updated["content"] = str(updated["content"]).strip()

        target_path = self._skill_path(updated)
        updated["file_path"] = str(target_path)
        self._write_skill_file(updated)
        if old_path.exists() and old_path != target_path:
            old_path.unlink()
        AgentSkillRepository.update(skill_id, updated)
        return self.get(skill_id)

    def archive(self, skill_id: str) -> dict:
        skill = self.get(skill_id)
        updated = {**skill, "status": "archived", "updated_at": datetime.now().astimezone().isoformat()}
        target = self._skill_path(updated)
        source = Path(skill["file_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists() and source != target:
            shutil.move(str(source), str(target))
        updated["file_path"] = str(target)
        self._write_skill_file(updated)
        AgentSkillRepository.update(skill_id, updated)
        return self.get(skill_id)

    def restore(self, skill_id: str) -> dict:
        skill = self.get(skill_id)
        updated = {**skill, "status": "active", "updated_at": datetime.now().astimezone().isoformat()}
        target = self._skill_path(updated)
        source = Path(skill["file_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists() and source != target:
            shutil.move(str(source), str(target))
        updated["file_path"] = str(target)
        self._write_skill_file(updated)
        AgentSkillRepository.update(skill_id, updated)
        return self.get(skill_id)

    def set_status(self, skill_id: str, status: str) -> dict:
        if status not in {"active", "disabled", "draft", "archived"}:
            raise HTTPException(status_code=400, detail="不支持的 Skill 状态")
        if status == "archived":
            return self.archive(skill_id)
        return self.update(skill_id, AgentSkillUpdate(status=status))

    def delete_physical_for_tests(self, skill_id: str) -> None:
        skill = AgentSkillRepository.get_by_id(skill_id)
        if skill and skill.get("file_path") and Path(skill["file_path"]).exists():
            Path(skill["file_path"]).unlink()
        AgentSkillRepository.delete(skill_id)

    def _ensure_agent(self, agent_id: str) -> None:
        if agent_id in VIRTUAL_SKILL_OWNERS:
            return
        if not AgentRepository.get_by_id(agent_id):
            raise HTTPException(status_code=404, detail="Agent 不存在")

    def _skill_path(self, skill: dict) -> Path:
        folder = "archived" if skill.get("status") == "archived" else "skills"
        slug = _slugify(skill.get("title") or "skill")
        return settings.artifacts_dir / "agent_skills" / _safe_segment(skill["agent_id"]) / folder / f"{slug}_{skill['id']}.md"

    def _write_skill_file(self, skill: dict) -> None:
        path = Path(skill["file_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        tags = "\n".join(f"  - {tag}" for tag in skill.get("tags", []))
        content = "\n".join(
            [
                "---",
                f"id: {skill['id']}",
                f"agent_id: {skill['agent_id']}",
                f"title: {_yaml_text(skill['title'])}",
                f"status: {skill['status']}",
                f"confidence: {skill.get('confidence', 0)}",
                f"source_run_id: {skill.get('source_run_id') or ''}",
                f"source_task_id: {skill.get('source_task_id') or ''}",
                f"created_at: {skill['created_at']}",
                f"updated_at: {skill['updated_at']}",
                f"last_used_at: {skill.get('last_used_at') or ''}",
                f"usage_count: {skill.get('usage_count', 0)}",
                f"failure_count: {skill.get('failure_count', 0)}",
                "tags:",
                tags or "  []",
                "---",
                "",
                f"# {skill['title']}",
                "",
                skill.get("description", ""),
                "",
                skill["content"],
                "",
            ]
        )
        path.write_text(content, encoding="utf-8")


def _safe_segment(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", value)[:80] or "agent"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fff]", "_", value).strip("_")
    return slug[:48] or "skill"


def _yaml_text(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


agent_skill_service = AgentSkillService()
