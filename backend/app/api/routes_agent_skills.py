from fastapi import APIRouter, Query

from ..models.agent_skill import AgentSkillCreate, AgentSkillUpdate
from ..services.agent_skill_service import agent_skill_service

router = APIRouter(prefix="/api/agent-skills", tags=["agent-skills"])


@router.get("")
async def list_agent_skills(
    agent_id: str | None = None,
    status: str | None = None,
    q: str | None = Query(default=None),
):
    return {"skills": agent_skill_service.list(agent_id=agent_id, status=status, q=q)}


@router.get("/owners")
async def list_agent_skill_owners():
    return {"owners": agent_skill_service.owners()}


@router.get("/{skill_id}")
async def get_agent_skill(skill_id: str):
    return {"skill": agent_skill_service.get(skill_id)}


@router.post("")
async def create_agent_skill(body: AgentSkillCreate):
    return {"skill": agent_skill_service.create(body)}


@router.patch("/{skill_id}")
async def update_agent_skill(skill_id: str, body: AgentSkillUpdate):
    return {"skill": agent_skill_service.update(skill_id, body)}


@router.delete("/{skill_id}")
async def archive_agent_skill(skill_id: str):
    return {"skill": agent_skill_service.archive(skill_id)}


@router.post("/{skill_id}/restore")
async def restore_agent_skill(skill_id: str):
    return {"skill": agent_skill_service.restore(skill_id)}


@router.post("/{skill_id}/disable")
async def disable_agent_skill(skill_id: str):
    return {"skill": agent_skill_service.set_status(skill_id, "disabled")}


@router.post("/{skill_id}/enable")
async def enable_agent_skill(skill_id: str):
    return {"skill": agent_skill_service.set_status(skill_id, "active")}
