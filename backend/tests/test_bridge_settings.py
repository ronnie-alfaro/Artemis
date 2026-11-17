from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.conversation_bridge import router
from app.application.rust_bridge import RustBridge

DEFAULT_URL = "http://artemis-bridge:8091"
SECONDARY_URL = "http://artemis-bridge-secondary:8091"


@pytest.mark.asyncio
async def test_settings_enable_and_change_only_trusted_bridge_urls():
    app = FastAPI()
    app.include_router(router)
    store = AsyncMock()
    store.settings.return_value = None

    async def save(settings):
        store.settings.return_value = settings

    store.save_settings.side_effect = save
    bridge = RustBridge(store, DEFAULT_URL, {}, AsyncMock(), lambda *_: [],
                        allowed_urls=(SECONDARY_URL,))
    app.state.conversation_bridge = bridge
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        path = "/api/v1/conversation-bridge/settings"
        response = await client.get(path)
        assert response.json() == {
            "enabled": False, "url": DEFAULT_URL, "allowed_urls": [DEFAULT_URL, SECONDARY_URL],
        }
        denied = await client.put(path, json={"enabled": True, "url": "http://postgres:5432"})
        assert denied.status_code == 422
        store.save_settings.assert_not_awaited()
        saved = await client.put(path, json={"enabled": True, "url": SECONDARY_URL})
        assert saved.status_code == 200
        assert await bridge.enabled()
        assert (await bridge.settings()).url == SECONDARY_URL
        disabled = await client.put(path, json={"enabled": False, "url": SECONDARY_URL})
        assert disabled.status_code == 200
        assert not await bridge.enabled()
    await bridge.close()
