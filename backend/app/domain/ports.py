from __future__ import annotations

from typing import Protocol

from app.domain.models import Agent, AgentRequest, AgentResponse, IncomingMessage, OutgoingMessage


class ChannelAdapter(Protocol):
    async def receive(self) -> IncomingMessage: ...
    async def send(self, message: OutgoingMessage) -> None: ...
    async def health(self) -> bool: ...


class AgentRunner(Protocol):
    definition: Agent

    async def run(self, request: AgentRequest) -> AgentResponse: ...
