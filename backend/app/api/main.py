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

from app.agents.antigravity import AntigravityAgent
from app.agents.codex import CodexAgent
from app.agents.karakeep import KarakeepAgent
from app.agents.seerr import SeerrAgent
from app.agents.status import StatusAgent
from app.agents.usenet import UsenetAgent
from app.api.antigravity import install_antigravity_routes
from app.api.codex import install_codex_routes
from app.api.notifications import install_notification_routes
from app.api.reminders import install_reminder_routes
from app.api.skills import install_skill_routes
from app.api.usenet import install_usenet_routes
from app.api.webhooks import install_webhook_routes, is_webhook_ingest
from app.application.antigravity import AntigravityDeliveryWorker, AntigravityQueue
from app.application.approvals import ApprovalStore
from app.application.codex import CodexDeliveryWorker, CodexQueue
from app.application.notifications import NotificationService
from app.application.orchestrator import (
    CapabilityPlanner,
    CompositeCapabilitySelector,
    DAGExecutor,
    Orchestrator,
    PlanningError,
)
from app.application.registry import AgentRegistry
from app.application.reminders import ReminderService, ReminderWorker
from app.application.skill_sessions import SkillSessionRouter
from app.application.webhook_notifications import WebhookNotificationWorker
from app.application.whatsapp import WhatsAppAgentRuntime
from app.domain.karakeep import (
    KarakeepClient,
    KarakeepClientError,
    KarakeepConfigurationInput,
    KarakeepConfigurationStatus,
    KarakeepSettings,
)
from app.domain.models import (
    APIError,
    ApprovalRequest,
    Channel,
    ChatRequest,
    ChatResponse,
    IncomingMessage,
    Tool,
)
from app.domain.notifications import NotificationSettings
from app.domain.seerr import (
    SeerrClient,
    SeerrClientError,
    SeerrConfigurationInput,
    SeerrConfigurationStatus,
    SeerrSettings,
)
from app.domain.usenet import UsenetClient, UsenetClientError
from app.domain.whatsapp import (
    WhatsAppAgentProfile,
    WhatsAppAgentProfileUpdate,
    WhatsAppChannelStatus,
    WhatsAppSettings,
    WhatsAppSkillBinding,
    WhatsAppSkillSelection,
)
from app.infrastructure.approval_state import PostgresApprovalStore
from app.infrastructure.karakeep_config import PostgresKarakeepConfigurationStore
from app.infrastructure.karakeep_http import HttpKarakeepClient
from app.infrastructure.karakeep_unconfigured import UnconfiguredKarakeepClient
from app.infrastructure.reminders import PostgresReminderStore
from app.infrastructure.seerr_config import PostgresSeerrConfigurationStore
from app.infrastructure.seerr_http import HttpSeerrClient
from app.infrastructure.seerr_unconfigured import UnconfiguredSeerrClient
from app.infrastructure.skill_presentations import PostgresSkillPresentationStore
from app.infrastructure.skill_sessions import PostgresSkillSessionStore
from app.infrastructure.usenet_config import PostgresUsenetConfigurationStore
from app.infrastructure.usenet_http import HttpUsenetClient
from app.infrastructure.webhook_events import PostgresWebhookEventStore
from app.infrastructure.whatsapp_http import HttpWhatsAppClient
from app.infrastructure.whatsapp_state import PostgresWhatsAppStateStore
from app.tools.antigravity import AntigravityTool
from app.tools.codex import CodexTool
from app.tools.karakeep import KarakeepBookmarkTool
from app.tools.notifications import SendNotificationTool
from app.tools.registry import ToolRegistry
from app.tools.reminders import CreateReminderTool
from app.tools.seerr import SeerrRequestTool

REQUESTS = Counter("artemis_requests_total", "Artemis requests", ["path", "status"])


def build_orchestrator(
    seerr_client: SeerrClient | None = None,
    karakeep_client: KarakeepClient | None = None,
    usenet_client: UsenetClient | None = None,
) -> Orchestrator:
    approvals = ApprovalStore()
    tools = ToolRegistry(approvals)
    agents = AgentRegistry()
    client = seerr_client or UnconfiguredSeerrClient()
    tools.register(SeerrRequestTool(client), authorized_agents={"seerr"})
    seerr_agent = SeerrAgent(client, tools, approvals)
    agents.register(seerr_agent)
    karakeep = karakeep_client or UnconfiguredKarakeepClient()
    tools.register(KarakeepBookmarkTool(karakeep), authorized_agents={"karakeep"})
    karakeep_agent = KarakeepAgent(karakeep, tools, approvals)
    usenet_agent = UsenetAgent(usenet_client, tools, approvals)
    agents.register(usenet_agent)
    codex_queue = CodexQueue(os.getenv("ARTEMIS_CODEX_QUEUE_DIR"))
    codex_agent = CodexAgent(codex_queue, tools)
    agents.register(codex_agent)
    antigravity_queue = AntigravityQueue(os.getenv("ARTEMIS_ANTIGRAVITY_QUEUE_DIR"))
    antigravity_agent = AntigravityAgent(antigravity_queue, tools)
    agents.register(antigravity_agent)
    skill_agents = (seerr_agent, karakeep_agent, usenet_agent, codex_agent, antigravity_agent)
    for create_tool in (False, True):
        tools.register(CodexTool(codex_queue, create_tool), authorized_agents={
            *(agent.definition.name for agent in skill_agents), "control-plane",
        })
    for create_tool in (False, True):
        tools.register(AntigravityTool(antigravity_queue, create_tool), authorized_agents={
            *(agent.definition.name for agent in skill_agents), "control-plane",
        })
    status_agent = StatusAgent(
        {
            capability.name: capability.help_text or capability.description
            for agent in skill_agents
            for capability in agent.definition.capabilities
        }
    )
    agents.register(status_agent)

    def reset_conversation(conversation_id: UUID) -> None:
        seerr_agent.reset_conversation(conversation_id)
        usenet_agent.reset_conversation(conversation_id)

    sessions = SkillSessionRouter(status_agent.presentations, approvals, reset_conversation)
    agents.register(karakeep_agent)
    notifications = NotificationService()
    tools.register(
        SendNotificationTool(notifications),
        authorized_agents={
            *(agent.definition.name for agent in skill_agents),
            "control-plane",
            "reminders",
        },
    )
    reminders = ReminderService(tools)
    tools.register(
        CreateReminderTool(reminders),
        authorized_agents={
            *(agent.definition.name for agent in skill_agents),
            "control-plane",
        },
    )
    selectors = CompositeCapabilitySelector(karakeep_agent, usenet_agent, seerr_agent)
    orchestrator = Orchestrator(CapabilityPlanner(agents, selectors), DAGExecutor(agents), sessions)
    orchestrator.reminders = reminders  # type: ignore[attr-defined]
    orchestrator.notifications = notifications  # type: ignore[attr-defined]
    orchestrator.approvals = approvals  # type: ignore[attr-defined]
    orchestrator.tools = tools  # type: ignore[attr-defined]
    orchestrator.seerr_agent = seerr_agent  # type: ignore[attr-defined]
    orchestrator.karakeep_agent = karakeep_agent  # type: ignore[attr-defined]
    orchestrator.usenet_agent = usenet_agent  # type: ignore[attr-defined]
    orchestrator.codex_queue = codex_queue  # type: ignore[attr-defined]
    orchestrator.antigravity_queue = antigravity_queue  # type: ignore[attr-defined]
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


def configured_karakeep_client() -> KarakeepClient | None:
    settings = configured_karakeep_settings()
    return HttpKarakeepClient(settings) if settings else None


def configured_karakeep_settings() -> KarakeepSettings | None:
    base_url, api_key = os.getenv("KARAKEEP_BASE_URL"), os.getenv("KARAKEEP_API_KEY")
    if not base_url or not api_key:
        return None
    return KarakeepSettings.model_validate({"base_url": base_url, "api_key": api_key})


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
    orchestrator = build_orchestrator(configured_seerr_client(), configured_karakeep_client())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        seerr_store: PostgresSeerrConfigurationStore | None = None
        karakeep_store: PostgresKarakeepConfigurationStore | None = None
        usenet_store: PostgresUsenetConfigurationStore | None = None
        usenet_client: HttpUsenetClient | None = None
        approval_store: PostgresApprovalStore | None = None
        saved_settings: SeerrSettings | None = None
        saved_karakeep_settings: KarakeepSettings | None = None
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
            karakeep_store = PostgresKarakeepConfigurationStore(database_url, encryption_key)
            await karakeep_store.start()
            saved_karakeep_settings = await karakeep_store.load()
            if saved_karakeep_settings:
                orchestrator.karakeep_agent.set_client(  # type: ignore[attr-defined]
                    HttpKarakeepClient(saved_karakeep_settings)
                )
            usenet_store = PostgresUsenetConfigurationStore(database_url, encryption_key)
            await usenet_store.start()
            saved_usenet = await usenet_store.load()
            if saved_usenet:
                usenet_client = HttpUsenetClient(saved_usenet)
                orchestrator.usenet_agent.set_client(usenet_client)  # type: ignore[attr-defined]
        webhook_store = None
        if database_url:
            webhook_store = PostgresWebhookEventStore(database_url)
            await webhook_store.start()
        app.state.webhook_events = webhook_store
        notifications: NotificationService = orchestrator.notifications  # type: ignore[attr-defined]
        notifications.store = webhook_store
        saved_notifications = (
            await webhook_store.load_notification_settings() if webhook_store else None
        )
        notifications.settings = saved_notifications or NotificationSettings(
            recipient_id=os.getenv("ARTEMIS_WEBHOOK_WHATSAPP_RECIPIENT") or None,
        )
        session_store = None
        if database_url:
            session_store = PostgresSkillSessionStore(database_url)
            await session_store.start()
            if orchestrator.skill_sessions:
                orchestrator.skill_sessions.store = session_store
        presentation_store = None
        if database_url:
            presentation_store = PostgresSkillPresentationStore(database_url)
            await presentation_store.start()
            orchestrator.registry.get("status").presentations.update(  # type: ignore[attr-defined]
                await presentation_store.load()
            )
        app.state.skill_presentations = presentation_store
        if database_url:
            approval_store = PostgresApprovalStore(database_url)
            await approval_store.start()
            orchestrator.approvals.hydrate(await approval_store.load())  # type: ignore[attr-defined]
            orchestrator.approvals.bind_persistence(approval_store.save)  # type: ignore[attr-defined]
        app.state.usenet_configuration = usenet_store
        app.state.usenet_client = usenet_client
        app.state.usenet_configured = usenet_client is not None
        app.state.seerr_configuration = seerr_store
        app.state.seerr_configured = bool(saved_settings or configured_seerr_settings())
        app.state.karakeep_configuration = karakeep_store
        app.state.karakeep_configured = bool(
            saved_karakeep_settings or configured_karakeep_settings()
        )
        runtime = configured_whatsapp_runtime(orchestrator)
        app.state.whatsapp = runtime
        if runtime:
            await runtime.start()
        notifier = None
        if runtime and webhook_store:
            notifier = WebhookNotificationWorker(
                webhook_store,
                runtime,
                os.getenv("ARTEMIS_WEBHOOK_WHATSAPP_RECIPIENT") or None,
            )
            notifier.configure(notifications.settings)
            notifications.recipients = runtime.notification_recipients
            await notifier.start()
        notifications.notifier = notifier
        app.state.webhook_notifier = notifier
        reminder_service: ReminderService = orchestrator.reminders  # type: ignore[attr-defined]
        reminder_store = None
        reminder_worker = None
        if database_url:
            reminder_store = PostgresReminderStore(database_url)
            await reminder_store.start()
            reminder_service.store = reminder_store
            reminder_worker = ReminderWorker(reminder_service)
            await reminder_worker.start()
        codex_delivery = None
        if runtime and orchestrator.codex_queue.directory:  # type: ignore[attr-defined]
            codex_delivery = CodexDeliveryWorker(orchestrator.codex_queue, runtime)  # type: ignore[attr-defined]
            await codex_delivery.start()
        antigravity_delivery = None
        if runtime and orchestrator.antigravity_queue.directory:  # type: ignore[attr-defined]
            antigravity_delivery = AntigravityDeliveryWorker(
                orchestrator.antigravity_queue, runtime  # type: ignore[attr-defined]
            )
            await antigravity_delivery.start()
        try:
            yield
        finally:
            if antigravity_delivery:
                await antigravity_delivery.stop()
            if codex_delivery:
                await codex_delivery.stop()
            if reminder_worker:
                await reminder_worker.stop()
            if reminder_store:
                await reminder_store.aclose()
            if notifier:
                await notifier.stop()
            if runtime:
                await runtime.stop()
            if seerr_store:
                await seerr_store.aclose()
            if karakeep_store:
                await karakeep_store.aclose()
            if app.state.usenet_client:
                await app.state.usenet_client.aclose()
            if usenet_store:
                await usenet_store.aclose()
            if approval_store:
                await approval_store.aclose()
            if presentation_store:
                await presentation_store.aclose()
            if session_store:
                await session_store.aclose()
            if webhook_store:
                await webhook_store.aclose()

    app = FastAPI(
        title="Artemis API", version="0.1.0", openapi_url="/api/v1/openapi.json", lifespan=lifespan
    )
    app.state.orchestrator = orchestrator
    install_usenet_routes(app, orchestrator)
    install_skill_routes(app, orchestrator)
    install_codex_routes(app, orchestrator.codex_queue)  # type: ignore[attr-defined]
    install_antigravity_routes(app, orchestrator.antigravity_queue)  # type: ignore[attr-defined]
    app.state.reminders = orchestrator.reminders  # type: ignore[attr-defined]
    install_reminder_routes(app, app.state.reminders)
    app.state.notifications = orchestrator.notifications  # type: ignore[attr-defined]
    install_notification_routes(app, app.state.notifications, orchestrator.tools)  # type: ignore[attr-defined]
    install_webhook_routes(app)
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
            and not is_webhook_ingest(request.method, request.url.path)
            and not secrets.compare_digest(
                request.headers.get("authorization", ""), f"Bearer {admin_token}"
            )
        ):
            return JSONResponse(
                status_code=401,
                content={
                    "code": "unauthorized",
                    "message": "Se requiere iniciar sesión",
                    "request_id": request_id,
                },
                headers={"x-request-id": request_id},
            )
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        REQUESTS.labels(path=request.url.path, status=str(response.status_code)).inc()
        return response

    @app.exception_handler(UsenetClientError)
    async def usenet_error(request: Request, exc: UsenetClientError) -> JSONResponse:
        return JSONResponse(
            status_code=502, content={"code": exc.code, "message": exc.safe_message}
        )

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
            raise HTTPException(status_code=404, detail="El agente de WhatsApp no está configurado")
        return runtime

    def available_capabilities() -> list[str]:
        registry: AgentRegistry = orchestrator.registry  # type: ignore[attr-defined]
        return sorted(
            capability.name for agent in registry.list_agents() for capability in agent.capabilities
        )

    def whatsapp_assignable_capabilities() -> list[str]:
        configured_capabilities = {
            "seerr.media": app.state.seerr_configured,
            "karakeep.bookmarks": app.state.karakeep_configured,
            "usenet.downloads": app.state.usenet_configured,
            "antigravity.assistant": orchestrator.antigravity_queue.available,  # type: ignore[attr-defined]
            "codex.assistant": orchestrator.codex_queue.available,  # type: ignore[attr-defined]
        }
        return [
            capability
            for capability in available_capabilities()
            if configured_capabilities.get(capability, False)
        ]

    def seerr_store() -> PostgresSeerrConfigurationStore:
        store: PostgresSeerrConfigurationStore | None = app.state.seerr_configuration
        if not store:
            raise HTTPException(
                status_code=503,
                detail=(
                    "La configuración cifrada de habilidades no está disponible en este despliegue"
                ),
            )
        return store

    def karakeep_store() -> PostgresKarakeepConfigurationStore:
        store: PostgresKarakeepConfigurationStore | None = app.state.karakeep_configuration
        if not store:
            raise HTTPException(
                status_code=503,
                detail=(
                    "La configuración cifrada de habilidades no está disponible en este despliegue"
                ),
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
            return SeerrConfigurationStatus(configured=False, last_test="Configura Seerr primero")
        client = HttpSeerrClient(settings)
        try:
            await client.test_connection()
        except SeerrClientError as error:
            return SeerrConfigurationStatus(
                configured=True,
                base_url=str(settings.base_url).rstrip("/"),
                credential_source="control plane" if saved else "environment",
                last_test=f"Error de conexión: {error.safe_message}",
            )
        finally:
            await client.aclose()
        return SeerrConfigurationStatus(
            configured=True,
            base_url=str(settings.base_url).rstrip("/"),
            credential_source="control plane" if saved else "environment",
            last_test="Conexión verificada",
        )

    @app.get("/api/v1/skills/karakeep/configuration", response_model=KarakeepConfigurationStatus)
    async def karakeep_configuration() -> KarakeepConfigurationStatus:
        saved = await karakeep_store().load()
        if saved:
            return KarakeepConfigurationStatus(
                configured=True,
                base_url=str(saved.base_url).rstrip("/"),
                credential_source="control plane",
            )
        environment = configured_karakeep_settings()
        if environment:
            return KarakeepConfigurationStatus(
                configured=True,
                base_url=str(environment.base_url).rstrip("/"),
                credential_source="environment",
            )
        return KarakeepConfigurationStatus(configured=False)

    @app.put("/api/v1/skills/karakeep/configuration", response_model=KarakeepConfigurationStatus)
    async def update_karakeep_configuration(
        payload: KarakeepConfigurationInput,
    ) -> KarakeepConfigurationStatus:
        saved = await karakeep_store().save(payload)
        orchestrator.karakeep_agent.set_client(HttpKarakeepClient(saved))  # type: ignore[attr-defined]
        app.state.karakeep_configured = True
        return KarakeepConfigurationStatus(
            configured=True,
            base_url=str(saved.base_url).rstrip("/"),
            credential_source="control plane",
        )

    @app.post(
        "/api/v1/skills/karakeep/configuration/test", response_model=KarakeepConfigurationStatus
    )
    async def test_karakeep_configuration() -> KarakeepConfigurationStatus:
        saved = await karakeep_store().load()
        settings = saved or configured_karakeep_settings()
        if not settings:
            return KarakeepConfigurationStatus(
                configured=False, last_test="Configura Karakeep primero"
            )
        client = HttpKarakeepClient(settings)
        try:
            await client.list_lists()
        except KarakeepClientError as error:
            return KarakeepConfigurationStatus(
                configured=True,
                base_url=str(settings.base_url).rstrip("/"),
                credential_source="control plane" if saved else "environment",
                last_test=f"Error de conexión: {error.safe_message}",
            )
        return KarakeepConfigurationStatus(
            configured=True,
            base_url=str(settings.base_url).rstrip("/"),
            credential_source="control plane" if saved else "environment",
            last_test="Conexión verificada",
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
        # The status capability is mandatory and returned by GET. Accept it on
        # round trips from clients, but persist only optional skill selections.
        optional_capabilities = set(payload.capabilities) - {"assistant.status"}
        unknown = sorted(optional_capabilities - set(available))
        if unknown:
            raise HTTPException(
                status_code=422, detail=f"Habilidades desconocidas o inactivas: {unknown}"
            )
        await runtime.set_capabilities(sorted(optional_capabilities))
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
        if approval.tool_name == "karakeep.create_bookmark" and orchestrator.karakeep_agent:  # type: ignore[attr-defined]
            await orchestrator.karakeep_agent.approve_operation(approval)  # type: ignore[attr-defined]
        if approval.agent_name == "usenet" and approval.tool_name.startswith("usenet."):
            await orchestrator.usenet_agent.approve_operation(approval)  # type: ignore[attr-defined]
        return orchestrator.approvals.get(approval_id)  # type: ignore[attr-defined,no-any-return]

    @app.post("/api/v1/approvals/{approval_id}/reject", response_model=ApprovalRequest)
    async def reject(approval_id: UUID) -> ApprovalRequest:
        orchestrator: Orchestrator = app.state.orchestrator
        rejected = orchestrator.approvals.reject(approval_id)  # type: ignore[attr-defined]
        await orchestrator.approvals.flush()  # type: ignore[attr-defined]
        return rejected  # type: ignore[no-any-return]

    return app


app = create_app()
