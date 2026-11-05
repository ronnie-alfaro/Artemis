from __future__ import annotations

from typing import Any

import httpx

from app.domain.models import OutgoingMessage
from app.domain.whatsapp import (
    WhatsAppAttachment,
    WhatsAppInbound,
    WhatsAppMessageType,
    WhatsAppSettings,
    WhatsAppUpdateBatch,
)


class WhatsAppTransportError(RuntimeError):
    """Safe provider failure; never contains request headers or response bodies."""


class HttpWhatsAppClient:
    def __init__(self, settings: WhatsAppSettings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client or httpx.AsyncClient(
            base_url=settings.base_url,
            headers={"Authorization": f"Bearer {settings.token.get_secret_value()}"},
            timeout=httpx.Timeout(40.0, connect=10.0),
        )

    async def updates(self, offset: int | None, timeout: int) -> WhatsAppUpdateBatch | None:
        params: dict[str, int] = {"limit": 50, "timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        response = await self._request("GET", "/updates", params=params)
        if response.status_code == 204:
            return None
        data = response.json()
        try:
            value = data["entry"][0]["changes"][0]["value"]
            messages = [self._inbound(item) for item in value.get("messages", [])]
            return WhatsAppUpdateBatch(messages=messages, next_offset=data["next_offset"])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise WhatsAppTransportError("WhatsApp devolvió una actualización no válida") from error

    async def mark_read(self, message_id: str, typing: bool = False) -> None:
        payload: dict[str, object] = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        if typing:
            payload["typing_indicator"] = {"type": "text"}
        await self._request("POST", "/statuses", json=payload)

    async def send_text(
        self, recipient_id: str, message: OutgoingMessage, reply_to: str | None = None
    ) -> str:
        payload: dict[str, object] = {
            "messaging_product": "whatsapp",
            "to": recipient_id,
            "type": "text",
            "text": {"body": message.content[:4096]},
        }
        if reply_to:
            payload["context"] = {"message_id": reply_to}
        response = await self._request("POST", "/messages", json=payload)
        try:
            return str(response.json()["messages"][0]["id"])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise WhatsAppTransportError(
                "WhatsApp devolvió una respuesta de envío no válida"
            ) from error

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise WhatsAppTransportError("WhatsApp no está disponible") from error
        if response.status_code >= 400:
            # Do not reflect potentially sensitive provider detail.
            raise WhatsAppTransportError(
                f"La solicitud a WhatsApp falló con HTTP {response.status_code}"
            )
        return response

    @staticmethod
    def _inbound(value: dict[str, Any]) -> WhatsAppInbound:
        message_type = WhatsAppMessageType(value["type"])
        attachment: list[WhatsAppAttachment] = []
        if message_type not in {WhatsAppMessageType.TEXT, WhatsAppMessageType.REACTION}:
            media = value[message_type.value]
            attachment = [
                WhatsAppAttachment(
                    id=media["id"],
                    mime_type=media.get("mime_type"),
                    sha256_base64=media.get("sha256"),
                    caption=media.get("caption"),
                    filename=media.get("filename"),
                    voice=media.get("voice"),
                )
            ]
        return WhatsAppInbound(
            id=value["id"],
            sender_id=value["from"],
            timestamp=value["timestamp"],
            type=message_type,
            text=value.get("text", {}).get("body"),
            reaction_emoji=value.get("reaction", {}).get("emoji"),
            reaction_message_id=value.get("reaction", {}).get("message_id"),
            attachments=attachment,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
