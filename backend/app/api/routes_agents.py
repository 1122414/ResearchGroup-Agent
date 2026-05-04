from fastapi import APIRouter, HTTPException
from ..storage.repositories import AgentRepository
from ..services.agent_registry import agent_registry

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
async def get_agents():
    agents = AgentRepository.get_all()
    return {"agents": agents}


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    agent = AgentRepository.get_by_id(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return {"agent": agent}
