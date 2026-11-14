from __future__ import annotations

import logging
from typing import Any

import httpx

from app.domain.models import OutgoingMessage
from app.domain.whatsapp import (
    WhatsAppInbound,
    WhatsAppMessageType,
    WhatsAppSettings,
    WhatsAppUpdateBatch,
)


class _RedactBotToken(logging.Filter):
    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = record.getMessage().replace(self._token, "[REDACTED]")
        record.args = ()
        return True


class HttpTelegramClient:
    """Bot API adapter to the durable messaging runtime; private authorized chats only."""

    def __init__(
        self, settings: WhatsAppSettings, allowed_user_ids: set[int],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not allowed_user_ids:
            raise ValueError("TELEGRAM_ALLOWED_USER_IDS must contain at least one user ID")
        self._redactor = _RedactBotToken(settings.token.get_secret_value())
        for name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
            logging.getLogger(name).addFilter(self._redactor)
        self._allowed = allowed_user_ids
        self._client = httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{settings.token.get_secret_value()}/",
            timeout=40, transport=transport,
        )

    async def _call(self, method: str, payload: dict[str, Any]) -> Any:
        # HTTP errors include the bot token in their URL. Never propagate their text/context.
        failed = False
        result: Any = None
        try:
            response = await self._client.post(method, json=payload)
            response.raise_for_status()
            body = response.json()
            if not body.get("ok"):
                failed = True
            else:
                result = body["result"]
        except (httpx.HTTPError, ValueError, KeyError):
            failed = True
        if failed:
            raise RuntimeError("Telegram Bot API request failed")
        return result

    async def test_connection(self) -> None:
        await self._call("getMe", {})
        webhook = await self._call("getWebhookInfo", {})
        if webhook.get("url"):
            raise ValueError("El bot tiene un webhook activo; retíralo antes de usar long polling.")

    async def updates(self, offset: int | None, timeout: int) -> WhatsAppUpdateBatch:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        updates = await self._call("getUpdates", payload)
        messages = []
        next_offset = offset or 0
        for update in updates:
            next_offset = max(next_offset, update["update_id"] + 1)
            message = update.get("message", {})
            chat, sender = message.get("chat", {}), message.get("from", {})
            if (chat.get("type") != "private" or sender.get("id") not in self._allowed
                    or sender.get("is_bot") or not message.get("text")):
                continue
            text = message["text"]
            if text == "/start":
                text = "hola"
            elif text == "/help":
                text = "ayuda"
            messages.append(WhatsAppInbound(
                id=str(update["update_id"]), sender_id=str(chat["id"]),
                timestamp=str(message.get("date", "")), type=WhatsAppMessageType.TEXT, text=text,
            ))
        return WhatsAppUpdateBatch(messages=messages, next_offset=next_offset)

    async def mark_read(self, message_id: str, typing: bool = False) -> None:
        pass

    async def send_text(
        self, recipient_id: str, message: OutgoingMessage, reply_to: str | None = None,
    ) -> str:
        if int(recipient_id) not in self._allowed:
            raise ValueError("Telegram recipient is not authorized")
        result = await self._call("sendMessage", {"chat_id": recipient_id, "text": message.content})
        return str(result["message_id"])

    async def aclose(self) -> None:
        await self._client.aclose()
        for name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
            logging.getLogger(name).removeFilter(self._redactor)
