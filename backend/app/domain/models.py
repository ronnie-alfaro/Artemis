from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class RiskLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    ADMIN = "admin"


class ExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"


class Permission(BaseModel):
    name: str
    description: str


class AgentCapability(BaseModel):
    name: str
    description: str
    dependencies: list[str] = Field(default_factory=list)
    help_text: str | None = Field(
        default=None,
        description="User-facing instructions shown when this capability is assigned to a channel.",
    )


class Channel(BaseModel):
    name: str
    version: str = "v1"
    allowed_capabilities: list[str] = Field(default_factory=list)
    assistant_greeting: str | None = Field(default=None, max_length=1024)
    assistant_persona: str | None = Field(default=None, max_length=8000)
    natural_conversation: bool = False
    agent_name: str | None = None


class Conversation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    channel: Channel
    created_at: datetime = Field(default_factory=utcnow)


class IncomingMessage(BaseModel):
    ephemeral_image_context: bool = False
    image_context: str = Field(default="", max_length=32000)
    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    channel: Channel
    content: str = Field(min_length=1, max_length=20_000)
    required_capabilities: list[str] = Field(default_factory=list)
    received_at: datetime = Field(default_factory=utcnow)


class ReactionOption(BaseModel):
    emoji: str
    label: str
    command: str


class OutgoingMessage(BaseModel):
    deferred: bool = False
    reaction_options: list[ReactionOption] = Field(default_factory=list, max_length=10)
    conversation_id: UUID
    content: str
    execution_id: UUID
    created_at: datetime = Field(default_factory=utcnow)


class RetryPolicy(BaseModel):
    max_attempts: int = Field(default=1, ge=1, le=3)


class Agent(BaseModel):
    name: str
    version: str
    purpose: str
    capabilities: list[AgentCapability]
    permissions: list[Permission] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.READ
    timeout_seconds: float = Field(default=10, gt=0, le=120)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    healthy: bool = True


class AgentRequest(BaseModel):
    execution_id: UUID
    node_id: str
    message: IncomingMessage
    context: dict[str, str] = Field(default_factory=dict)


class AgentResult(BaseModel):
    reaction_options: list[ReactionOption] = Field(default_factory=list, max_length=10)
    agent_name: str
    content: str
    sources: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    result: AgentResult


class AgentExecution(BaseModel):
    node_id: str
    agent_name: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result: AgentResult | None = None


class Tool(BaseModel):
    input_example: dict[str, object] = Field(default_factory=dict)
    requires_approval: bool = True
    name: str
    description: str
    permissions: list[Permission] = Field(default_factory=list)
    risk_level: RiskLevel
    timeout_seconds: float = Field(default=10, gt=0, le=120)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)


class ToolInvocation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tool_name: str
    agent_name: str
    input: dict[str, object]
    risk_level: RiskLevel
    approval_id: UUID | None = None


class ToolResult(BaseModel):
    invocation_id: UUID
    output: dict[str, str]


class ApprovalRequest(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    agent_name: str
    tool_name: str
    parameters: dict[str, str]
    risk_level: RiskLevel
    reason: str
    expires_at: datetime
    conversation_id: UUID
    operation_id: UUID
    status: ApprovalStatus = ApprovalStatus.PENDING
    result: dict[str, str] | None = None


class PlanNode(BaseModel):
    id: str
    capability: str
    agent_name: str
    dependencies: list[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    nodes: list[PlanNode]
    status: ExecutionStatus = ExecutionStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)


class ModelProvider(BaseModel):
    name: str
    model: str
    healthy: bool = True


class APIError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    request_id: str


class ChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    conversation_id: UUID | None = None
    required_capabilities: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    message: OutgoingMessage
    plan: ExecutionPlan
    executions: list[AgentExecution]
