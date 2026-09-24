from app.domain.models import Agent
from app.domain.ports import AgentRunner


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentRunner] = {}
        self._unhealthy_plugins: dict[str, str] = {}

    def register(self, agent: AgentRunner) -> None:
        if agent.definition.name in self._agents:
            raise ValueError(f"duplicate agent: {agent.definition.name}")
        self._agents[agent.definition.name] = agent

    def discover(self, capability: str) -> list[AgentRunner]:
        return [
            agent
            for agent in self._agents.values()
            if agent.definition.healthy
            and any(item.name == capability for item in agent.definition.capabilities)
        ]

    def get(self, name: str) -> AgentRunner:
        return self._agents[name]

    def list_agents(self) -> list[Agent]:
        return [agent.definition for agent in self._agents.values()]

    def health(self) -> bool:
        return all(agent.definition.healthy for agent in self._agents.values())
