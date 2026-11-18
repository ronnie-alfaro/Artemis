from __future__ import annotations

from datetime import date
from typing import Literal

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.domain.models import RiskLevel, Tool, ToolInvocation, ToolResult
from app.domain.tool_calling import Arguments

BASE_URL = "https://api.terraquakeapi.com/v1/earthquakes"


class Query(Arguments):
    period: Literal["recent", "today", "last-week", "month"] | None = None
    magnitude: float | None = Field(default=None, ge=0, le=10)
    region: str | None = Field(default=None, min_length=1, max_length=80)
    start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    limit: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def validate_filters(self) -> Query:
        if (self.start is None) != (self.end is None):
            raise ValueError("Indica ambas fechas.")
        if (self.start and self.end
                and date.fromisoformat(self.start) > date.fromisoformat(self.end)):
            raise ValueError("La fecha inicial debe ser anterior o igual a la final.")
        if sum(value is not None for value in
               (self.period, self.magnitude, self.region, self.start)) > 1:
            raise ValueError("Elige un filtro por consulta.")
        return self

    def endpoint(self) -> tuple[str, dict[str, str | int | float]]:
        params: dict[str, str | int | float] = {"limit": self.limit}
        if self.magnitude is not None:
            return "magnitude", {**params, "mag": self.magnitude}
        if self.region:
            return "region", {**params, "region": self.region}
        if self.start and self.end:
            return "range-time", {**params, "startdate": self.start, "enddate": self.end}
        return self.period or "recent", params


class EventProperties(BaseModel):
    eventId: int
    time: str
    mag: float | None = None
    place: str


class Geometry(BaseModel):
    coordinates: tuple[float, float, float]


class Event(BaseModel):
    properties: EventProperties
    geometry: Geometry | None = None


class EventPage(BaseModel):
    success: Literal[True]
    payload: list[Event]
    totalEarthquakes: int | None = None


class TerraQuakeError(ValueError):
    pass


class TerraQuakeTool:
    definition = Tool(
        name="terraquake.query",
        description="Consulta sismos de TerraQuake por periodo, magnitud mínima o región italiana.",
        risk_level=RiskLevel.READ,
        requires_approval=False,
        input_example={"period": "recent", "limit": 5},
    )

    async def invoke(self, invocation: ToolInvocation) -> ToolResult:
        query = Query.model_validate(invocation.input)
        endpoint, params = query.endpoint()
        try:
            async with httpx.AsyncClient(timeout=7, follow_redirects=False) as client:
                response = await client.get(f"{BASE_URL}/{endpoint}", params=params)
                response.raise_for_status()
            page = EventPage.model_validate_json(response.content)
        except httpx.HTTPStatusError as error:
            messages = {
                400: "TerraQuake rechazó los filtros. Revisa la región o las fechas.",
                401: "TerraQuake exige autenticación para esta consulta.",
                403: "TerraQuake denegó el acceso a esta consulta.",
                429: "TerraQuake alcanzó su límite de consultas. Inténtalo más tarde.",
            }
            raise TerraQuakeError(messages.get(
                error.response.status_code, "TerraQuake no pudo completar la consulta."
            )) from None
        except (httpx.RequestError, ValidationError):
            raise TerraQuakeError("No pude obtener una respuesta válida de TerraQuake.") from None
        return ToolResult(invocation_id=invocation.id, output={
            "page": page.model_copy(update={
                "payload": page.payload[:query.limit],
            }).model_dump_json(),
            "source": str(response.url),
        })
