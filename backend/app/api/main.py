from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, make_asgi_app
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.agents.fake.agent import FakeAgent
from app.agents.fake.tool import FakeEchoTool
from app.application.orchestrator import CapabilityPlanner, DAGExecutor, Orchestrator, PlanningError
from app.application.registry import AgentRegistry
from app.domain.models import APIError, Channel, ChatRequest, ChatResponse, IncomingMessage
from app.tools.registry import ToolRegistry

REQUESTS = Counter("artemis_requests_total", "Artemis requests", ["path", "status"])


def build_orchestrator() -> Orchestrator:
    tools = ToolRegistry()
    tools.register(FakeEchoTool())
    agents = AgentRegistry()
    agents.register(FakeAgent(tools))
    return Orchestrator(CapabilityPlanner(agents), DAGExecutor(agents))


def create_app() -> FastAPI:
    app = FastAPI(title="Artemis API", version="0.1.0", openapi_url="/api/v1/openapi.json")
    app.state.orchestrator = build_orchestrator()
    app.mount("/metrics", make_asgi_app())

    @app.middleware("http")
    async def correlation_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid4()))
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

    return app


app = create_app()
