"""Admin configuration and read-only simulation through the live Rust engine."""
import os
import re
from typing import Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

from app.api.conversation_bridge import ProviderId, bridge_for, current_bot
from app.application.context_builder import propose_core
from app.application.rust_bridge import INSTRUCTIONS
from app.domain.context_builder import ContextSettings
from app.domain.models import Channel, IncomingMessage
from app.domain.whatsapp import DEFAULT_PERSONA

router = APIRouter(prefix="/api/v1/context-builder", tags=["context-builder"])
AgentChannel = Literal["whatsapp", "telegram"]


def admin(request: Request):
    if not os.getenv("ARTEMIS_ADMIN_TOKEN"):
        raise HTTPException(503, "Configura ARTEMIS_ADMIN_TOKEN para administrar el contexto.")
    return bridge_for(request)


def active_agent(bridge, channel: AgentChannel):
    bot = current_bot(bridge, channel)
    runtime = bridge.controllers[channel].runtime
    if runtime is None:
        raise HTTPException(409, "Inicia el canal para consultar su perfil.")
    return bot, runtime


class PersonaProposal(BaseModel):
    extended: str = Field(min_length=1, max_length=8000)


@router.post("/persona/propose")
async def persona_proposal(value: PersonaProposal, request: Request):
    admin(request)
    return {"core": propose_core(value.extended)}


class ProfileEdit(BaseModel):
    core: str = Field(min_length=1, max_length=2000)
    extended: str = Field(min_length=1, max_length=8000)


class Simulation(BaseModel):
    channel: AgentChannel
    provider: ProviderId
    message: str = Field(min_length=1, max_length=10000)
    conversation: UUID | None = None


class RevisionInput(BaseModel):
    revision: int = Field(ge=1)


def check_scope(scope: str, bridge) -> str:
    if scope == "global" or re.fullmatch(r"provider:[a-z][a-z0-9-]{0,31}", scope):
        return scope
    for channel in ("whatsapp", "telegram"):
        connection = bridge.controllers[channel].connection
        if connection and scope == f"agent:{channel}:{connection.agent_name}":
            return scope
    raise HTTPException(422, "Ámbito de configuración inválido.")


@router.get("/settings")
async def settings(request: Request, scope: str = "global"):
    bridge = admin(request)
    check_scope(scope, bridge)
    store = bridge.context_source.store
    revisions = await store.revisions(scope)
    config = revisions[0]["config"] if revisions else {}
    return {"config": config, "defaults": ContextSettings(), "revisions": revisions,
            "internal_auth_configured": len(bridge.context_token) >= 32,
            "agents": {channel: controller.connection.agent_name
                       for channel, controller in bridge.controllers.items()
                       if controller.connection},
            "providers": await bridge.store.catalog()}


@router.put("/settings")
async def save_settings(value: dict[str, Any], request: Request, scope: str = "global"):
    bridge = admin(request)
    check_scope(scope, bridge)
    if len(str(value)) > 20000:
        raise HTTPException(422, "Configuración demasiado extensa.")
    try:
        revision = await bridge.context_source.store.save(scope, value)
    except (ValidationError, TypeError, AttributeError, ValueError) as error:
        raise HTTPException(422, "La configuración o sus reservas son incompatibles.") from error
    return {"revision": revision}


@router.post("/settings/restore")
async def restore_settings(value: RevisionInput, request: Request, scope: str = "global"):
    bridge = admin(request)
    check_scope(scope, bridge)
    store = bridge.context_source.store
    selected = next((item for item in await store.revisions(scope)
                     if item["revision"] == value.revision), None)
    if selected is None:
        raise HTTPException(404, "Revisión no disponible.")
    try:
        revision = await store.save(scope, selected["config"], value.revision)
    except ValidationError as error:
        raise HTTPException(
            422, "La revisión no es compatible con los ajustes actuales.",
        ) from error
    return {"revision": revision}


@router.get("/persona/{channel}")
async def persona(channel: AgentChannel, request: Request):
    bridge = admin(request)
    bot, runtime = active_agent(bridge, channel)
    original = await runtime.persona() or DEFAULT_PERSONA
    agent = f"{channel}:{bot}"
    core, extended, version = await bridge.context_source.persona(agent, original, 150)
    try:
        versions = await bridge.context_source.versions(agent)
    except Exception:
        versions = []
    return {"core": core, "extended": extended, "original": original, "version": version,
            "versions": sorted(versions, key=lambda item: item["updated_at"], reverse=True)[:30],
            "suggestion": propose_core(extended)}


@router.put("/persona/{channel}")
async def update_persona(channel: AgentChannel, value: ProfileEdit, request: Request):
    bridge = admin(request)
    bot, runtime = active_agent(bridge, channel)
    store = bridge.context_source.store
    providers = await bridge.store.providers(channel, bot) or ["codex"]
    effective = await store.effective(f"agent:{channel}:{bot}", providers)
    core, extended = value.core.strip(), value.extended.strip()
    if not core or not extended or any(
        len(core.encode()) > options.components["core"].maximum * options.bytes_per_token
        for options in effective.values()
    ):
        raise HTTPException(422, "El Core debe caber en el presupuesto de todos los proveedores.")
    original = await runtime.persona() or DEFAULT_PERSONA
    try:
        version = await bridge.context_source.save_persona(
            f"{channel}:{bot}", original, extended, core,
        )
    except Exception as error:
        raise HTTPException(503, "No se pudo guardar el perfil en Chroma.") from error
    if extended != original:
        await runtime.set_persona(extended)
    return {"revision": version}


@router.get("/metrics")
async def metrics(request: Request):
    return await admin(request).context_source.store.metrics()


@router.get("/conversations/{channel}")
async def conversations(channel: AgentChannel, request: Request):
    bridge = admin(request)
    bot, _ = active_agent(bridge, channel)
    rows = await bridge.store.pool.fetch("""
        SELECT conversation,max(created_at) AS updated_at FROM bridge_turns
        WHERE channel=$1 AND bot=$2 GROUP BY conversation ORDER BY updated_at DESC LIMIT 50
    """, channel, bot)
    return [dict(row) for row in rows]


@router.post("/simulate")
async def simulate(value: Simulation, request: Request):
    bridge = admin(request)
    bot, runtime = active_agent(bridge, value.channel)
    if len(bridge.context_token) < 32:
        raise HTTPException(503, "Configura la conexión autenticada con Rust.")
    if value.provider not in await bridge.store.catalog():
        raise HTTPException(422, "Proveedor no registrado.")
    source = bridge.context_source
    if value.conversation:
        saved = await source.store.turn(value.channel, bot, value.conversation)
        if not saved:
            raise HTTPException(404, "Conversación no encontrada para este agente.")
        row = {**dict(saved), "ordinal": saved["ordinal"] + 1}
    else:
        row = {"channel": value.channel, "bot": bot, "conversation": UUID(int=0), "ordinal": 0}

    conversation_agent = request.app.state.orchestrator.registry.get("conversation")
    capabilities = [name for name in await runtime.capabilities()
                    if name not in {"codex.assistant", "antigravity.assistant"}]
    message = IncomingMessage(channel=Channel(name=value.channel),
                              conversation_id=row["conversation"], content=value.message)
    if value.conversation:
        catalog = await conversation_agent.catalog_for(message, capabilities)
    else:
        catalog = conversation_agent.catalog(
            [name for name in capabilities if name != "curiosity.api"],
        )
    context = {
        "persona": await runtime.persona() or DEFAULT_PERSONA, "greeting": await runtime.greeting(),
        "message": value.message, "image_context": "", "skills": catalog, "observations": [],
        "actions_remaining": 4,
    }
    if value.conversation:
        context["approvals"] = [
            {"id": str(item.id), "agent": item.agent_name}
            for item in bridge.pending_approvals(value.conversation)
        ]
    settings = await source.store.effective(f"agent:{value.channel}:{bot}", [value.provider])
    payload, revision, _ = await source.prepare(row, context, INSTRUCTIONS, settings, persist=False)
    try:
        response = await bridge.request(
            "POST", "/v1/context/preview", timeout=5, context_auth=True,
            payload={"provider": value.provider, "context": payload},
        )
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 422:
            raise HTTPException(422, "El contexto protegido excede el presupuesto.") from error
        raise HTTPException(503, "El bridge no aceptó la simulación.") from error
    except httpx.HTTPError as error:
        raise HTTPException(503, "El bridge no está disponible.") from error
    return {**response.json(), "persona_revision": revision, "runtime_enabled":
            settings[value.provider].enabled}
