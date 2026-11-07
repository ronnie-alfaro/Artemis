from __future__ import annotations

import json
import os
import re

import httpx

from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult


class GitHubError(Exception):
    """Safe error for chat and API callers."""


class GitHubTool:
    definition = Tool(
        name="github.read",
        description="Consulta repositorios, commits, ramas, issues y pull requests de GitHub.",
        risk_level=RiskLevel.READ,
    )

    def __init__(self, token: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._token = token if token is not None else os.getenv("GITHUB_TOKEN", "")
        self._transport = transport

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        action = invocation.input.get("action", "repos")
        repo = invocation.input.get("repo", "")
        page = invocation.input.get("page", 1)
        if type(page) is not int or not 1 <= page <= 1000:
            raise ValueError("La página debe estar entre 1 y 1000.")
        if action not in {"repos", "commits", "branches", "issues", "pulls"}:
            raise ValueError("Operación GitHub no válida.")
        if action != "repos" and (
            not isinstance(repo, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repo)
            or repo.split("/")[1] in {".", ".."}
        ):
            raise ValueError("Indica el repositorio como propietario/repositorio.")
        if not self._token:
            raise GitHubError("GitHub necesita GITHUB_TOKEN en el entorno del servicio.")
        path = "/user/repos" if action == "repos" else f"/repos/{repo}/{action}"
        params = {"per_page": "10", "page": str(page)}
        if action == "repos":
            params["sort"] = "updated"
        try:
            async with httpx.AsyncClient(
                base_url="https://api.github.com", timeout=15, transport=self._transport,
                headers={"Authorization": f"Bearer {self._token}",
                         "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28"},
            ) as client:
                response = await client.get(path, params=params)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list):
                    raise ValueError("Unexpected response")
                for row in data:
                    if not isinstance(row, dict):
                        raise ValueError("Unexpected item")
                    if action == "commits":
                        commit = row.get("commit", {})
                        if (
                            not isinstance(commit, dict)
                            or not isinstance(commit.get("message", ""), str)
                            or not isinstance(row.get("sha", ""), str)
                        ):
                            raise ValueError("Unexpected commit")
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            messages = {
                401: "GitHub rechazó la credencial.",
                403: "GitHub denegó el acceso o alcanzó el límite de consultas.",
                404: "No encuentro ese repositorio o no tienes acceso.",
                409: "El repositorio está vacío; todavía no tiene commits.",
                429: "GitHub pide una pausa: límite de consultas alcanzado.",
            }
            message = messages.get(status, "GitHub no pudo completar la consulta.")
            raise GitHubError(message) from None
        except (httpx.RequestError, ValueError):
            raise GitHubError("No pude leer GitHub. Prueba de nuevo en un momento.") from None
        items = []
        for row in data:
            if action == "issues" and "pull_request" in row:
                continue
            if action == "commits":
                title = row.get("commit", {}).get("message", "").split("\n")[0]
                label = f"{row.get('sha', '')[:7]} {title}"
            else:
                label = row.get("full_name") or row.get("title") or row.get("name", "")
            items.append({"title": str(label)[:180], "url": row.get("html_url", "")})
        return ToolResult(invocation_id=invocation.id, output={
            "items": json.dumps(items), "page": str(page),
            "has_more": str('rel="next"' in response.headers.get("link", "")).lower(),
        })
