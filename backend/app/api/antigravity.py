from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.application.antigravity import AntigravityQueue


def install_antigravity_routes(app: FastAPI, queue: AntigravityQueue) -> None:
    @app.get("/api/v1/skills/antigravity/configuration")
    async def configuration() -> dict[str, object]:
        return {
            "configured": queue.available,
            "connected": queue.available,
            "conversation_ready": queue.conversation_available,
            "last_test": "Antigravity conectado" if queue.available else "Antigravity sin conexión",
        }

    @app.get("/api/v1/skills/antigravity/jobs")
    async def jobs() -> list[dict[str, object]]:
        return [
            job.model_dump(mode="json", exclude={"conversation_id", "channel"})
            for job in queue.recent()
        ]

    @app.get("/api/v1/skills/antigravity/jobs/{job_id}/patch")
    async def patch(job_id: UUID) -> FileResponse:
        job = queue.load(job_id)
        if not job or not job.has_patch:
            raise HTTPException(404, "No hay un parche disponible para esa petición.")
        path = queue.path(job_id, ".patch")
        if not path.is_file():
            raise HTTPException(404, "El parche no está disponible.")
        return FileResponse(path, media_type="text/plain", filename=f"artemis-{job_id}.patch")
