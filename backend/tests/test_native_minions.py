import asyncio
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.application.approvals import ApprovalStore
from app.application.minions import LocalExecutor, MinionDispatcher
from app.application.native_tools import Arguments, CallContext, FunctionCall, NativeTools
from app.domain.models import RiskLevel, Tool, ToolResult
from app.tools.registry import ApprovalRequired, ToolRegistry


class Payload(Arguments):
    value: str


class Runner:
    definition = Tool(name="test.write", description="Test", risk_level=RiskLevel.WRITE)

    async def invoke(self, invocation):
        await asyncio.sleep(0)
        return ToolResult(invocation_id=invocation.id, output={"ok": "yes"})


def setup():
    approvals = ApprovalStore()
    registry = ToolRegistry(approvals)
    registry.register(Runner(), {"test"})
    native = NativeTools(registry, approvals, lambda capability, context: True)
    native.register("test.write", "test", Payload)
    context = CallContext(agent="test", conversation_id=uuid4(), capabilities={"test"})
    call = FunctionCall(id="call1", name="test.write", arguments={"value": "hello"})
    return native, approvals, context, call


@pytest.mark.asyncio
async def test_approval_binding_and_single_use():
    native, approvals, context, call = setup()
    with pytest.raises(ApprovalRequired):
        await native.execute(call, context)
    approval = native.request_approval(call, context)
    approvals.approve(approval.id)
    changed = call.model_copy(update={"arguments": {"value": "different"}})
    with pytest.raises(ApprovalRequired):
        await native.execute(changed, context, approval.id)
    results = await asyncio.gather(
        *[native.execute(call, context, approval.id) for _ in range(2)], return_exceptions=True
    )
    assert sum(isinstance(item, ToolResult) for item in results) == 1
    assert sum(isinstance(item, ApprovalRequired) for item in results) == 1


def test_schema_and_policy():
    native, _, context, call = setup()
    schema = native.schemas(context)[0]["function"]["parameters"]
    assert schema["additionalProperties"] is False
    with pytest.raises(ValidationError):
        native.request_approval(call.model_copy(update={"arguments": {"value": 1}}), context)
    context.capabilities.clear()
    assert native.schemas(context) == []
    with pytest.raises(PermissionError):
        native.request_approval(call, context)


@pytest.mark.asyncio
async def test_dispatch_telemetry_and_failure():
    native, approvals, context, call = setup()
    dispatcher = MinionDispatcher({"local": LocalExecutor(native)})
    approval = native.request_approval(call, context)
    approvals.approve(approval.id)
    job = dispatcher.submit(call, context, approval_id=approval.id)
    await asyncio.gather(*list(dispatcher.tasks.values()))
    assert dispatcher.jobs[job.id].state == "completed"
    assert [e.minion["state"] for e in dispatcher.events] == [
        "pending",
        "running",
        "completed",
    ]
    assert "context" not in dispatcher.events[-1].minion
    failed = dispatcher.submit(call, context)
    await asyncio.gather(*list(dispatcher.tasks.values()))
    assert dispatcher.jobs[failed.id].state == "failed"
    with pytest.raises(ValueError):
        dispatcher.submit(call, context, target="untrusted")
    await dispatcher.close()


@pytest.mark.asyncio
async def test_parallelism_capacity_and_cancellation():
    _, _, context, call = setup()
    gate = asyncio.Event()
    started = []

    class Blocking:
        async def execute(self, job):
            started.append(job.id)
            await gate.wait()
            return {}

    dispatcher = MinionDispatcher({"local": Blocking()}, parallelism=2, capacity=2)
    dispatcher.submit(call, context)
    dispatcher.submit(call, context)
    with pytest.raises(RuntimeError):
        dispatcher.submit(call, context)
    await asyncio.sleep(0)
    assert len(started) == 2
    await dispatcher.close()
    assert all(job.state == "cancelled" for job in dispatcher.jobs.values())


@pytest.mark.asyncio
async def test_http_transport_contract():
    import httpx

    from app.domain.minions import MinionJob
    from app.infrastructure.minion_transports import HTTPExecutor, SSHExecutor

    _, _, context, call = setup()

    def respond(request):
        import json

        payload = json.loads(request.content)
        assert payload["call"]["name"] == "test.write"
        assert "approval_id" not in payload
        assert request.headers["Authorization"] == "Bearer test-only"
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        executor = HTTPExecutor("https://worker.invalid/jobs", "test-only", client)
        job = MinionJob(
            name="Hermes",
            mythology="griega",
            task="test.write",
            target="remote",
            call=call,
            context=context,
        )
        assert await executor.execute(job) == {"ok": True}
        with pytest.raises(ValueError):
            HTTPExecutor("http://worker.invalid", "test-only", client)
    with pytest.raises(ValueError):
        SSHExecutor("-oProxyCommand=bad")


@pytest.mark.asyncio
async def test_revocation_and_timeout():
    native, approvals, context, call = setup()
    approval = native.request_approval(call, context)
    approvals.approve(approval.id)
    native.enabled = lambda capability, ctx: False
    with pytest.raises(PermissionError):
        await native.execute(call, context, approval.id)

    class Slow:
        async def execute(self, job):
            await asyncio.Event().wait()
            return {}

    dispatcher = MinionDispatcher({"local": Slow()}, timeout=0.01)
    job = dispatcher.submit(call, context)
    await asyncio.gather(*list(dispatcher.tasks.values()))
    assert dispatcher.jobs[job.id].state == "failed"
    await dispatcher.close()
