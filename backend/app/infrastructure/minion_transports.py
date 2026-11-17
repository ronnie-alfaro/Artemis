"""Explicitly configured remote workers; no model-supplied URLs or shell commands."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.domain.minions import MinionJob


def worker_payload(job: MinionJob) -> dict[str, Any]:
    # Remote approvals are deliberately not forwarded: worker trust and approval stores differ.
    return {
        "job_id": str(job.id),
        "call": job.call.model_dump(mode="json"),
        "context": job.context.model_dump(mode="json"),
    }


class HTTPExecutor:
    def __init__(self, endpoint: str, token: str, client: httpx.AsyncClient) -> None:
        url = urlsplit(endpoint)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Remote workers require an HTTPS endpoint without userinfo")
        self.endpoint, self._token, self.client = endpoint, token, client

    async def execute(self, job: MinionJob) -> dict[str, Any]:
        response = await self.client.post(
            self.endpoint,
            json=worker_payload(job),
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=120,
            follow_redirects=False,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Invalid worker response")
        return result


class SSHExecutor:
    def __init__(self, host: str) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.@-]{0,252}", host):
            raise ValueError("Invalid configured SSH host")
        self.host = host

    async def execute(self, job: MinionJob) -> dict[str, Any]:
        process = await asyncio.create_subprocess_exec(
            "ssh",
            "-T",
            "-oBatchMode=yes",
            "-oStrictHostKeyChecking=yes",
            "-oConnectTimeout=10",
            "--",
            self.host,
            "artemis-minion-worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await process.communicate(json.dumps(worker_payload(job)).encode())
            if process.returncode:
                raise RuntimeError("SSH worker failed")
            result = json.loads(stdout)
            if not isinstance(result, dict):
                raise ValueError("Invalid worker response")
            return result
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
