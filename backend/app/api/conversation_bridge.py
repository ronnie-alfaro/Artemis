from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, StringConstraints

from app.application.rust_bridge import RustBridge
from app.infrastructure.conversation_bridge import BridgeSettings

router = APIRouter(prefix="/api/v1/conversation-bridge", tags=["conversation-bridge"])
Channel = Literal["whatsapp", "telegram"]
ProviderId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,31}$")]


class SettingsInput(BaseModel):
    enabled: bool
    url: str = Field(min_length=1, max_length=1024)


class SettingsView(SettingsInput):
    allowed_urls: tuple[str, ...]


class Routing(BaseModel):
    providers: list[ProviderId] = Field(max_length=8)


class Provider(BaseModel):
    id: ProviderId
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


def bridge_for(request: Request) -> RustBridge:
    bridge = getattr(request.app.state, "conversation_bridge", None)
    if not isinstance(bridge, RustBridge):
        raise HTTPException(503, "El bridge conversacional no está configurado.")
    return bridge


def current_bot(bridge: RustBridge, channel: Channel) -> str:
    connection = bridge.controllers[channel].connection
    if connection is None:
        raise HTTPException(404, "Este canal no tiene un bot configurado.")
    return connection.agent_name


@router.get("/settings")
async def get_settings(request: Request) -> SettingsView:
    bridge = bridge_for(request)
    settings = await bridge.settings()
    return SettingsView(
        enabled=settings.enabled, url=settings.url, allowed_urls=bridge.allowed_urls,
    )


@router.put("/settings")
async def save_settings(request: Request, value: SettingsInput) -> SettingsView:
    bridge = bridge_for(request)
    if value.url not in bridge.allowed_urls:
        raise HTTPException(422, "Selecciona una dirección autorizada para el bridge.")
    await bridge.store.save_settings(BridgeSettings(value.enabled, value.url))
    return SettingsView(**value.model_dump(), allowed_urls=bridge.allowed_urls)


@router.get("/providers")
async def get_providers(request: Request) -> dict[str, list[dict[str, str]] | list[str]]:
    bridge = bridge_for(request)
    catalog, installed = await bridge.store.catalog(), await bridge.installed()
    return {
        "providers": [
            {"id": key, "label": label, "status": installed.get(key, "missing")}
            for key, label in catalog.items()
        ],
        "discoverable": sorted(set(installed) - set(catalog)),
    }


@router.post("/providers", status_code=201)
async def register_provider(request: Request, value: Provider) -> None:
    bridge = bridge_for(request)
    if value.id in {"codex", "agy"} or value.id not in await bridge.installed():
        raise HTTPException(422, "Selecciona un adaptador CLI adicional instalado en el bridge.")
    await bridge.store.register(value.id, value.label)


@router.post("/providers/{provider}/probe")
async def probe(request: Request, provider: ProviderId) -> dict[str, bool]:
    bridge = bridge_for(request)
    if provider not in await bridge.store.catalog() or provider not in await bridge.installed():
        raise HTTPException(404, "El adaptador CLI no está disponible.")
    try:
        response = await bridge.request("POST", "/v1/decide", timeout=55, payload={
            "providers": [provider],
            "prompt": (
                'Devuelve únicamente este JSON: {"reply":"ok","capability":"","command":""}.'
            ),
            "capabilities": [],
            "actions_remaining": 0,
        })
        available = response.json().get("provider") == provider
    except (httpx.HTTPError, ValueError):
        available = False
    return {"ready": available}


@router.get("/routing/{channel}")
async def get_routing(request: Request, channel: Channel) -> dict[str, str | list[str] | None]:
    bridge = bridge_for(request)
    bot = current_bot(bridge, channel)
    return {
        "providers": await bridge.store.providers(channel, bot),
        "last_provider": await bridge.store.last_provider(channel, bot),
    }


@router.put("/routing/{channel}")
async def set_routing(request: Request, channel: Channel, value: Routing) -> Routing:
    bridge = bridge_for(request)
    bot = current_bot(bridge, channel)
    if len(set(value.providers)) != len(value.providers):
        raise HTTPException(422, "Cada proveedor debe aparecer una sola vez.")
    if set(value.providers) - (await bridge.store.catalog()).keys():
        raise HTTPException(422, "Selecciona únicamente proveedores registrados.")
    await bridge.store.save_providers(channel, bot, value.providers)
    return value
