from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, make_asgi_app
from pydantic import SecretStr
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.agents.seerr import SeerrAgent
from app.agents.status import StatusAgent
from app.application.approvals import ApprovalStore
from app.application.orchestrator import CapabilityPlanner, DAGExecutor, Orchestrator, PlanningError
from app.application.registry import AgentRegistry
from app.application.whatsapp import WhatsAppAgentRuntime
from app.domain.models import (
    APIError,
    ApprovalRequest,
    Channel,
    ChatRequest,
    ChatResponse,
    IncomingMessage,
    Tool,
)
from app.domain.seerr import (
    SeerrClient,
    SeerrClientError,
    SeerrConfigurationInput,
    SeerrConfigurationStatus,
    SeerrSettings,
)
from app.domain.whatsapp import (
    WhatsAppAgentProfile,
    WhatsAppAgentProfileUpdate,
    WhatsAppChannelStatus,
    WhatsAppSettings,
    WhatsAppSkillBinding,
    WhatsAppSkillSelection,
)
from app.infrastructure.approval_state import PostgresApprovalStore
from app.infrastructure.seerr_config import PostgresSeerrConfigurationStore
from app.infrastructure.seerr_http import HttpSeerrClient
from app.infrastructure.seerr_unconfigured import UnconfiguredSeerrClient
from app.infrastructure.whatsapp_http import HttpWhatsAppClient
from app.infrastructure.whatsapp_state import PostgresWhatsAppStateStore
from app.tools.registry import ToolRegistry
from app.tools.seerr import SeerrRequestTool

REQUESTS = Counter("artemis_requests_total", "Artemis requests", ["path", "status"])


def build_orchestrator(seerr_client: SeerrClient | None = None) -> Orchestrator:
    approvals = ApprovalStore()
    tools = ToolRegistry(approvals)
    agents = AgentRegistry()
    agents.register(StatusAgent())
    client = seerr_client or UnconfiguredSeerrClient()
    tools.register(SeerrRequestTool(client), authorized_agents={"seerr"})
    selector = SeerrAgent(client, tools, approvals)
    agents.register(selector)
    orchestrator = Orchestrator(CapabilityPlanner(agents, selector), DAGExecutor(agents))
    orchestrator.approvals = approvals  # type: ignore[attr-defined]
    orchestrator.tools = tools  # type: ignore[attr-defined]
    orchestrator.seerr_agent = selector  # type: ignore[attr-defined]
    orchestrator.registry = agents  # type: ignore[attr-defined]
    return orchestrator


def configured_seerr_client() -> SeerrClient | None:
    base_url, api_key = os.getenv("SEERR_BASE_URL"), os.getenv("SEERR_API_KEY")
    if not base_url or not api_key:
        return None
    return HttpSeerrClient(SeerrSettings.model_validate({"base_url": base_url, "api_key": api_key}))


def configured_seerr_settings() -> SeerrSettings | None:
    base_url, api_key = os.getenv("SEERR_BASE_URL"), os.getenv("SEERR_API_KEY")
    if not base_url or not api_key:
        return None
    return SeerrSettings.model_validate({"base_url": base_url, "api_key": api_key})


def configured_whatsapp_runtime(orchestrator: Orchestrator) -> WhatsAppAgentRuntime | None:
    token = os.getenv("WHATSAPP_AGENT_TOKEN")
    if not token:
        return None
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required when WHATSAPP_AGENT_TOKEN is configured")
    settings = WhatsAppSettings(
        agent_name=os.getenv("WHATSAPP_AGENT_NAME", "primary"),
        token=SecretStr(token),
    )
    state = PostgresWhatsAppStateStore(database_url)
    client = HttpWhatsAppClient(settings)
    return WhatsAppAgentRuntime(settings, client, state, orchestrator.handle)


def create_app() -> FastAPI:
    orchestrator = build_orchestrator(configured_seerr_client())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        seerr_store: PostgresSeerrConfigurationStore | None = None
        approval_store: PostgresApprovalStore | None = None
        saved_settings: SeerrSettings | None = None
        database_url, encryption_key = (
            os.getenv("DATABASE_URL"),
            os.getenv("ARTEMIS_CONFIG_ENCRYPTION_KEY"),
        )
        if database_url and encryption_key:
            seerr_store = PostgresSeerrConfigurationStore(database_url, encryption_key)
            await seerr_store.start()
            saved_settings = await seerr_store.load()
            if saved_settings:
                orchestrator.seerr_agent.set_client(HttpSeerrClient(saved_settings))  # type: ignore[attr-defined]
        if database_url:
            approval_store = PostgresApprovalStore(database_url)
            await approval_store.start()
            orchestrator.approvals.hydrate(await approval_store.load())  # type: ignore[attr-defined]
            orchestrator.approvals.bind_persistence(approval_store.save)  # type: ignore[attr-defined]
        app.state.seerr_configuration = seerr_store
        app.state.seerr_configured = bool(saved_settings or configured_seerr_settings())
        runtime = configured_whatsapp_runtime(orchestrator)
        app.state.whatsapp = runtime
        if runtime:
            await runtime.start()
        try:
            yield
        finally:
            if runtime:
                await runtime.stop()
            if seerr_store:
                await seerr_store.aclose()
            if approval_store:
                await approval_store.aclose()

    app = FastAPI(
        title="Artemis API", version="0.1.0", openapi_url="/api/v1/openapi.json", lifespan=lifespan
    )
    app.state.orchestrator = orchestrator
    app.mount("/metrics", make_asgi_app())

    @app.middleware("http")
    async def correlation_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid4()))
        admin_token = os.getenv("ARTEMIS_ADMIN_TOKEN")
        public_paths = {"/api/v1/health", "/api/v1/ready", "/api/v1/auth/status"}
        if (
            admin_token
            and request.url.path.startswith("/api/v1/")
            and request.url.path not in public_paths
            and not secrets.compare_digest(
                request.headers.get("authorization", ""), f"Bearer {admin_token}"
            )
        ):
            return JSONResponse(
                status_code=401,
                content={
                    "code": "unauthorized",
                    "message": "Authentication required",
                    "request_id": request_id,
                },
                headers={"x-request-id": request_id},
            )
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        REQUESTS.labels(path=request.url.path, status=str(response.status_code)).inc()
        return response

    @app.exception_handler(PlanningError)
    async def planning_error(request: Request, exc: PlanningError) -> JSONResponse:
        error = APIError(
            code="planning_error",
            message=str(exc),
            request_id=request.headers.get("x-request-id", "unknown"),
        )
        return JSONResponse(status_code=422, content=error.model_dump())

    @app.get("/api/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/ready")
    async def ready() -> dict[str, str]:
        return {"status": "ready"}

    @app.get("/api/v1/auth/status")
    async def auth_status() -> dict[str, bool]:
        return {"authentication_required": bool(os.getenv("ARTEMIS_ADMIN_TOKEN"))}

    @app.get("/api/v1/channels/whatsapp", response_model=WhatsAppChannelStatus)
    async def whatsapp_status() -> WhatsAppChannelStatus:
        runtime: WhatsAppAgentRuntime | None = app.state.whatsapp
        return runtime.status() if runtime else WhatsAppChannelStatus(configured=False)

    def configured_whatsapp_runtime_for(agent_name: str) -> WhatsAppAgentRuntime:
        runtime: WhatsAppAgentRuntime | None = app.state.whatsapp
        if not runtime or runtime.status().agent_name != agent_name:
            raise HTTPException(status_code=404, detail="WhatsApp agent is not configured")
        return runtime

    def available_capabilities() -> list[str]:
        registry: AgentRegistry = orchestrator.registry  # type: ignore[attr-defined]
        return sorted(
            capability.name for agent in registry.list_agents() for capability in agent.capabilities
        )

    def whatsapp_assignable_capabilities() -> list[str]:
        if not app.state.seerr_configured:
            return []
        return [
            capability
            for capability in available_capabilities()
            if capability != "assistant.status"
        ]

    def seerr_store() -> PostgresSeerrConfigurationStore:
        store: PostgresSeerrConfigurationStore | None = app.state.seerr_configuration
        if not store:
            raise HTTPException(
                status_code=503,
                detail="Local encrypted skill configuration is unavailable in this deployment",
            )
        return store

    @app.get("/api/v1/skills/seerr/configuration", response_model=SeerrConfigurationStatus)
    async def seerr_configuration() -> SeerrConfigurationStatus:
        saved = await seerr_store().load()
        if saved:
            return SeerrConfigurationStatus(
                configured=True,
                base_url=str(saved.base_url).rstrip("/"),
                credential_source="control plane",
            )
        environment = configured_seerr_settings()
        if environment:
            return SeerrConfigurationStatus(
                configured=True,
                base_url=str(environment.base_url).rstrip("/"),
                credential_source="environment",
            )
        return SeerrConfigurationStatus(configured=False)

    @app.put("/api/v1/skills/seerr/configuration", response_model=SeerrConfigurationStatus)
    async def update_seerr_configuration(
        payload: SeerrConfigurationInput,
    ) -> SeerrConfigurationStatus:
        saved = await seerr_store().save(payload)
        orchestrator.seerr_agent.set_client(HttpSeerrClient(saved))  # type: ignore[attr-defined]
        app.state.seerr_configured = True
        return SeerrConfigurationStatus(
            configured=True,
            base_url=str(saved.base_url).rstrip("/"),
            credential_source="control plane",
        )

    @app.post("/api/v1/skills/seerr/configuration/test", response_model=SeerrConfigurationStatus)
    async def test_seerr_configuration() -> SeerrConfigurationStatus:
        saved = await seerr_store().load()
        settings = saved or configured_seerr_settings()
        if not settings:
            return SeerrConfigurationStatus(configured=False, last_test="Configure Seerr first")
        client = HttpSeerrClient(settings)
        try:
            await client.search_media("Artemis connection check")
        except SeerrClientError as error:
            return SeerrConfigurationStatus(
                configured=True,
                base_url=str(settings.base_url).rstrip("/"),
                credential_source="control plane" if saved else "environment",
                last_test=f"Connection failed: {error.code.value}",
            )
        return SeerrConfigurationStatus(
            configured=True,
            base_url=str(settings.base_url).rstrip("/"),
            credential_source="control plane" if saved else "environment",
            last_test="Connection verified",
        )

    @app.get("/api/v1/agents/whatsapp/{agent_name}/skills", response_model=WhatsAppSkillBinding)
    async def whatsapp_skills(agent_name: str) -> WhatsAppSkillBinding:
        runtime = configured_whatsapp_runtime_for(agent_name)
        return WhatsAppSkillBinding(
            agent_name=agent_name,
            capabilities=await runtime.capabilities(),
            available_capabilities=whatsapp_assignable_capabilities(),
        )

    @app.put("/api/v1/agents/whatsapp/{agent_name}/skills", response_model=WhatsAppSkillBinding)
    async def update_whatsapp_skills(
        agent_name: str, payload: WhatsAppSkillSelection
    ) -> WhatsAppSkillBinding:
        runtime = configured_whatsapp_runtime_for(agent_name)
        available = whatsapp_assignable_capabilities()
        unknown = sorted(set(payload.capabilities) - set(available))
        if unknown:
            raise HTTPException(
                status_code=422, detail=f"Unknown or inactive capabilities: {unknown}"
            )
        await runtime.set_capabilities(payload.capabilities)
        return WhatsAppSkillBinding(
            agent_name=agent_name,
            capabilities=await runtime.capabilities(),
            available_capabilities=available,
        )

    @app.get("/api/v1/agents/whatsapp/{agent_name}/profile", response_model=WhatsAppAgentProfile)
    async def whatsapp_profile(agent_name: str) -> WhatsAppAgentProfile:
        runtime = configured_whatsapp_runtime_for(agent_name)
        return WhatsAppAgentProfile(agent_name=agent_name, greeting=await runtime.greeting())

    @app.put("/api/v1/agents/whatsapp/{agent_name}/profile", response_model=WhatsAppAgentProfile)
    async def update_whatsapp_profile(
        agent_name: str, payload: WhatsAppAgentProfileUpdate
    ) -> WhatsAppAgentProfile:
        runtime = configured_whatsapp_runtime_for(agent_name)
        await runtime.set_greeting(payload.greeting.strip())
        return WhatsAppAgentProfile(agent_name=agent_name, greeting=await runtime.greeting())

    @app.post("/api/v1/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest) -> ChatResponse:
        conversation_id = payload.conversation_id or uuid4()
        message = IncomingMessage(
            conversation_id=conversation_id,
            channel=Channel(name="rest"),
            content=payload.content,
            required_capabilities=payload.required_capabilities,
        )
        orchestrator: Orchestrator = app.state.orchestrator
        return await orchestrator.handle(message)

    @app.get("/api/v1/tools", response_model=list[Tool])
    async def list_tools() -> list[Tool]:
        orchestrator: Orchestrator = app.state.orchestrator
        return orchestrator.tools.list_tools()  # type: ignore[attr-defined,no-any-return]

    @app.get("/api/v1/approvals", response_model=list[ApprovalRequest])
    async def list_approvals() -> list[ApprovalRequest]:
        orchestrator: Orchestrator = app.state.orchestrator
        return orchestrator.approvals.all_approvals()  # type: ignore[attr-defined,no-any-return]

    @app.get("/api/v1/approvals/{approval_id}", response_model=ApprovalRequest)
    async def get_approval(approval_id: UUID) -> ApprovalRequest:
        orchestrator: Orchestrator = app.state.orchestrator
        return orchestrator.approvals.get(approval_id)  # type: ignore[attr-defined,no-any-return]

    @app.post("/api/v1/approvals/{approval_id}/approve", response_model=ApprovalRequest)
    async def approve(approval_id: UUID) -> ApprovalRequest:
        orchestrator: Orchestrator = app.state.orchestrator
        approval = orchestrator.approvals.approve(approval_id)  # type: ignore[attr-defined]
        await orchestrator.approvals.flush()  # type: ignore[attr-defined]
        if approval.tool_name == "seerr.create_request" and orchestrator.seerr_agent:  # type: ignore[attr-defined]
            await orchestrator.seerr_agent.approve_operation(approval)  # type: ignore[attr-defined]
        return orchestrator.approvals.get(approval_id)  # type: ignore[attr-defined,no-any-return]

    @app.post("/api/v1/approvals/{approval_id}/reject", response_model=ApprovalRequest)
    async def reject(approval_id: UUID) -> ApprovalRequest:
        orchestrator: Orchestrator = app.state.orchestrator
        rejected = orchestrator.approvals.reject(approval_id)  # type: ignore[attr-defined]
        await orchestrator.approvals.flush()  # type: ignore[attr-defined]
        return rejected  # type: ignore[no-any-return]

    return app


app = create_app()
