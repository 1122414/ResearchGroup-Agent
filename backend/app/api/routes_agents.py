from fastapi import APIRouter, HTTPException

from ..core.logger import logger
from ..services.agent_registry import agent_registry
from ..storage.repositories import AgentRepository

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
async def get_agents():
    logger.debug("[API] get_agents")
    agents = AgentRepository.get_all()
    return {"agents": agents}


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    logger.debug("[API] get_agent | agent_id=%s", agent_id)
    agent = AgentRepository.get_by_id(agent_id)
    if not agent:
        logger.warning("[API] get_agent | agent_id=%s not found", agent_id)
        raise HTTPException(status_code=404, detail="Agent 不存在")
    return {"agent": agent}
