from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from app.api.main import build_orchestrator
from app.domain.models import Channel, IncomingMessage, RiskLevel, ToolInvocation
from app.tools.github import GitHubError, GitHubTool


def test_pagination_auth_and_commits() -> None:
    def respond(request):
        assert request.url.host == "api.github.com"
        assert request.url.path == "/repos/owner/repo/commits"
        assert request.url.params["page"] == "2"
        assert request.headers["authorization"] == "Bearer test-secret"
        return httpx.Response(200, json=[
            {"sha": "abcdef123", "commit": {"message": "Fix bug\nDetails"},
             "html_url": "https://github.com/owner/repo/commit/abcdef123"}
        ], headers={"Link": '<https://api.github.com/next>; rel="next"'})

    result = asyncio.run(GitHubTool("test-secret", httpx.MockTransport(respond)).invoke(
        ToolInvocation(tool_name="github.read", agent_name="github", risk_level=RiskLevel.READ,
                       input={"action": "commits", "repo": "owner/repo", "page": 2})
    ))
    assert json.loads(result.output["items"])[0]["title"] == "abcdef1 Fix bug"
    assert result.output["has_more"] == "true"


@pytest.mark.parametrize("status", [401, 403, 404, 409, 429, 500])
def test_errors_never_expose_remote_body_or_token(status) -> None:
    tool = GitHubTool("test-secret", httpx.MockTransport(
        lambda request: httpx.Response(status, text="test-secret")
    ))
    with pytest.raises(GitHubError) as error:
        asyncio.run(tool.invoke(ToolInvocation(
            tool_name="github.read", agent_name="github", risk_level=RiskLevel.READ,
            input={"action": "repos"},
        )))
    assert "test-secret" not in str(error.value)


@pytest.mark.parametrize("parameters", [
    {"action": "delete"}, {"action": "commits", "repo": "../.."},
    {"action": "commits", "repo": "https://evil.test"},
    {"action": "repos", "page": 0}, {"action": "repos", "page": True},
])
def test_invalid_inputs_are_rejected_before_network(parameters) -> None:
    with pytest.raises(ValueError):
        asyncio.run(GitHubTool("test-secret").invoke(ToolInvocation(
            tool_name="github.read", agent_name="github", risk_level=RiskLevel.READ,
            input=parameters,
        )))


def test_skill_activation_and_chat_use_registered_tool() -> None:
    async def scenario():
        runtime = build_orchestrator()
        runtime.tools.replace(GitHubTool("test-secret", httpx.MockTransport(
            lambda request: httpx.Response(200, json=[
                {"full_name": "owner/repo", "html_url": "https://github.com/owner/repo"}
            ])
        )), authorized_agents={"github"})
        conversation = uuid4()

        async def send(content):
            return await runtime.handle(IncomingMessage(
                conversation_id=conversation, channel=Channel(name="whatsapp"),
                content=content,
            ))

        assert "GitHub activo" in (await send("utiliza github")).message.content
        assert "owner/repo" in (await send("repos")).message.content
        assert "commits dueño/repo" in (await send("ayuda")).message.content

    asyncio.run(scenario())


@pytest.mark.parametrize("payload", [
    [None],
    ["unexpected"],
    [{"commit": None}],
    [{"commit": {"message": None}}],
    [{"sha": None, "commit": {"message": "Fix"}}],
])
def test_malformed_commits_return_safe_error(payload) -> None:
    tool = GitHubTool("test-secret", httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)
    ))
    with pytest.raises(GitHubError, match="No pude leer GitHub"):
        asyncio.run(tool.invoke(ToolInvocation(
            tool_name="github.read", agent_name="github", risk_level=RiskLevel.READ,
            input={"action": "commits", "repo": "owner/repo"},
        )))
