from __future__ import annotations

import re
import unicodedata

from app.domain.models import (
    Agent,
    AgentCapability,
    AgentRequest,
    AgentResponse,
    AgentResult,
    IncomingMessage,
    RiskLevel,
    ToolInvocation,
)
from app.domain.skills import TERRAQUAKE_CAPABILITY
from app.tools.registry import ToolRegistry
from app.tools.terraquake import EventPage, Query, TerraQuakeError

HELP = (
    "TerraQuake · Pregúntame, por ejemplo: «¿Cuáles son los últimos 3 sismos?», "
    "«¿Qué terremotos hubo hoy?», «Sismos de magnitud 5 o superior», "
    "«¿Qué sismos hubo en Calabria?» o «Sismos entre 2026-01-01 y 2026-01-07». "
    "Usa un filtro por consulta. Las regiones disponibles son italianas."
)
_SEISMIC = re.compile(r"\b(?:sismos?|terremotos?|temblores?|seismos?|actividad sismica)\b")
_REGION = re.compile(
    r"\ben\s+(?:la region (?:de )?)?([a-z][a-z '-]+?)"
    r"(?=\s+(?:segun|por favor|hoy|esta|este|entre|desde|con|de magnitud)\b|[?!.,;]|$)"
)


def _normalize(text: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFD", text.casefold())
        if not unicodedata.combining(char)
    )


def _query(text: str) -> Query | None:
    values: dict[str, object] = {}
    count = re.search(r"\b(\d+)\s+(?:ultimos?\s+)?" + _SEISMIC.pattern, text)
    if count:
        values["limit"] = int(count[1])
    dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if dates:
        if len(dates) != 2:
            raise ValueError("Indica dos fechas en formato AAAA-MM-DD.")
        values.update(start=dates[0], end=dates[1])
    magnitude = re.search(r"\bmagnitud\s+(?:minima\s+|de\s+)?(\d+(?:[.,]\d+)?)", text)
    if magnitude:
        values["magnitude"] = float(magnitude[1].replace(",", "."))
    region = _REGION.search(text)
    if region and region[1].strip() != "terraquake":
        values["region"] = region[1].strip()
    periods = (
        ("today", r"\bhoy\b"),
        ("last-week", r"\b(?:ultima semana|ultimos 7 dias)\b"),
        ("month", r"\b(?:este mes|ultimo mes)\b"),
    )
    for period, pattern in periods:
        if re.search(pattern, text):
            values["period"] = period
            break
    if re.search(r"\b(?:ayer|entre magnitudes|profundidad|menor|inferior|exacta|estadisticas)\b",
                 text):
        return None
    if not any(key != "limit" for key in values) and not re.search(
        r"\b(?:ultim[oa]s?|recientes?)\b", text
    ):
        return None
    return Query.model_validate(values)


class TerraQuakeAgent:
    definition = Agent(
        name="terraquake",
        version="0.1.0",
        purpose="Consulta el catálogo público de sismos de TerraQuake.",
        capabilities=[AgentCapability(
            name=TERRAQUAKE_CAPABILITY,
            description="Consulta sismos recientes, por fecha, magnitud mínima o región italiana.",
            help_text=HELP,
        )],
        risk_level=RiskLevel.READ,
    )

    def __init__(self, tools: ToolRegistry) -> None:
        self._tools = tools

    def select(self, message: IncomingMessage) -> str | None:
        text = _normalize(message.content)
        return TERRAQUAKE_CAPABILITY if _SEISMIC.search(text) else None

    async def run(self, request: AgentRequest) -> AgentResponse:
        content = HELP
        try:
            query = _query(_normalize(request.message.content))
            if query:
                result = await self._tools.invoke(ToolInvocation(
                    tool_name="terraquake.query",
                    agent_name=self.definition.name,
                    risk_level=RiskLevel.READ,
                    input=query.model_dump(),
                ))
                page = EventPage.model_validate_json(result.output["page"])
                total = page.totalEarthquakes
                lines = [f"TerraQuake · {len(page.payload)} resultados mostrados"
                         + (f" de {total}" if total is not None else "")]
                for event in page.payload:
                    item = event.properties
                    magnitude = f"M {item.mag:g}" if item.mag is not None else "magnitud sin dato"
                    depth = (
                        f" · {event.geometry.coordinates[2]:g} km de profundidad"
                        if event.geometry else ""
                    )
                    lines.append(
                        f"• {item.place} · {magnitude}{depth} · {item.time} · ID {item.eventId}"
                    )
                if not page.payload:
                    lines.append("No encontré sismos para este filtro.")
                lines.append(result.output["source"])
                content = "\n".join(lines)
        except TerraQuakeError as error:
            content = str(error)
        except ValueError:
            content = (
                "Revisa las fechas, usa un solo filtro y pide entre 1 y 20 resultados. " + HELP
            )
        return AgentResponse(result=AgentResult(
            agent_name=self.definition.name,
            content=content,
            metadata={"execution_id": str(request.execution_id)},
        ))
