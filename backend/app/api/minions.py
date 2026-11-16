"""Administrative telemetry endpoints; mutations stay behind the application policy boundary."""

from fastapi import FastAPI, Query

from app.application.minions import MinionDispatcher
from app.application.native_tools import NativeTools


def install_minion_routes(app: FastAPI, dispatcher: MinionDispatcher, native: NativeTools) -> None:
    @app.get("/api/v1/minions")
    async def list_minions() -> list[dict[str, object]]:
        return [job.model_dump(mode="json") for job in dispatcher.jobs.values()]

    @app.get("/api/v1/minions/events")
    async def minion_events(after: int = Query(default=0, ge=0)) -> dict[str, object]:
        events = list(dispatcher.events)
        return {
            "events": [event.model_dump(mode="json") for event in events if event.sequence > after],
            "oldest_sequence": events[0].sequence if events else 0,
            "latest_sequence": events[-1].sequence if events else 0,
        }

    @app.get("/api/v1/tools/contracts")
    async def contracts() -> list[dict[str, object]]:
        # Administrative inventory, not the filtered catalog sent to a model.
        return [
            {"name": name, "capability": capability, "parameters": arguments.model_json_schema()}
            for name, (capability, arguments) in native.contracts.items()
        ]
