from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.tmdb import Query, TmdbAgent, natural_query
from app.api.main import build_orchestrator
from app.domain.models import Channel, IncomingMessage
from app.infrastructure.tmdb import TmdbClient


@pytest.mark.asyncio
async def test_upcoming_horror_uses_regional_theatrical_dates(monkeypatch):
    client = TmdbClient("fake")
    get = AsyncMock(return_value={"results": [{
        "id": 123, "title": "Example", "release_date": "2027-10-03", "poster_path": "/a.jpg",
    }]})
    monkeypatch.setattr(client, "get", get)
    result = await TmdbAgent(client).execute(Query(
        action="upcoming", media="movie", genre="horror", region="CR",
        start_date="2027-10-01", end_date="2027-10-31",
    ))
    args, params = get.await_args
    assert args == ("discover/movie",)
    assert params["with_genres"] == 27
    assert params["region"] == "CR"
    assert params["with_release_type"] == "3|2"
    assert params["release_date.lte"] == "2027-10-31"
    assert "TMDB 123" in result
    assert "https://image.tmdb.org/t/p/w342/a.jpg" in result


@pytest.mark.asyncio
async def test_no_announced_episode_preserves_series_status(monkeypatch):
    query = natural_query("¿Cuándo dan capítulo nuevo de la serie Severance?")
    assert query and query.action == "next_episode" and query.query == "Severance"
    client = TmdbClient("fake")
    monkeypatch.setattr(client, "get", AsyncMock(side_effect=[
        {"results": [{"id": 456, "name": "Separación", "original_name": "Severance"}]},
        {"id": 456, "name": "Separación", "original_name": "Severance",
         "status": "Returning Series", "next_episode_to_air": None},
    ]))
    result = await TmdbAgent(client).execute(query)
    assert "Separación (Severance)" in result
    assert "no registra un próximo episodio anunciado" in result
    assert "Returning Series" in result


@pytest.mark.asyncio
async def test_seerr_watchlist_uses_tmdb_id_and_existing_approval(monkeypatch):
    from test_seerr import FakeSeerr

    seerr = FakeSeerr()
    submit = AsyncMock(return_value={"tmdbId": 123, "mediaType": "movie"})
    monkeypatch.setattr(seerr, "api_request", submit, raising=False)
    orchestrator = build_orchestrator(seerr_client=seerr)
    channel = Channel(name="whatsapp", allowed_capabilities=["tmdb.catalog", "seerr.media"])
    conversation = uuid4()

    async def send(content):
        return await orchestrator.handle(IncomingMessage(
            conversation_id=conversation, channel=channel, content=content,
        ))

    assert "TMDB activo" in (await send("utiliza TMDB")).message.content
    approval = await send('seerr api POST /api/v1/watchlist {"tmdbId":123,"mediaType":"movie"}')
    assert "confirmo" in approval.message.content
    submit.assert_not_awaited()
    assert "Operación Seerr ejecutada" in (await send("confirmo")).message.content
    operation = submit.await_args.args[0]
    assert (operation.method, operation.path, operation.body) == (
        "POST", "/api/v1/watchlist", {"tmdbId": 123, "mediaType": "movie"},
    )


@pytest.mark.asyncio
async def test_tmdb_chat_returns_the_execution_id(monkeypatch):
    monkeypatch.setenv("TMDB_RAT", "fake")
    get = AsyncMock(return_value={"results": [{
        "id": 123, "name": "Example", "poster_path": "/a.jpg",
    }]})
    monkeypatch.setattr(TmdbClient, "get", get)
    orchestrator = build_orchestrator()
    response = await orchestrator.handle(IncomingMessage(
        conversation_id=uuid4(),
        channel=Channel(name="rest"),
        content="tmdb tendencias de series",
        required_capabilities=["tmdb.catalog"],
    ))

    assert "Tendencias" in response.message.content
    assert "https://image.tmdb.org/t/p/w342/a.jpg" in response.message.content
    assert response.executions[0].result is not None
    assert response.executions[0].result.metadata["execution_id"] == str(
        response.message.execution_id
    )
    get.assert_awaited_once_with("trending/tv/week", language="es", page=1)
