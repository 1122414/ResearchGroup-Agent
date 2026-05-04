import json
from pathlib import Path
from ..core.config import settings
from ..storage.repositories import AgentRepository


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, dict] = {}

    def load_seed_agents(self):
        seed_file = settings.data_dir / "seed_agents.json"
        if not seed_file.exists():
            return
        agents = json.loads(seed_file.read_text(encoding="utf-8"))
        AgentRepository.seed(agents)
        self._agents = {a["id"]: a for a in agents}

    def get_all(self) -> list[dict]:
        return AgentRepository.get_all()

    def get_graduate_agents(self) -> list[dict]:
        return [a for a in self.get_all() if a["type"] in ("researcher", "engineer", "experimenter", "analyst", "writer")]

    def get_by_id(self, agent_id: str) -> dict | None:
        return AgentRepository.get_by_id(agent_id)

    def update_status(self, agent_id: str, status: str, current_load: float = 0.0):
        AgentRepository.update_status(agent_id, status, current_load)


agent_registry = AgentRegistry()
