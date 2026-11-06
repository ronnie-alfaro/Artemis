from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator


class SkillPresentation(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=240)

    @field_validator("name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return " ".join(value.split()) if isinstance(value, str) else value


DEFAULT_PRESENTATIONS = {
    "github": SkillPresentation(
        name="GitHub", description="Consulta repositorios, commits, ramas, issues y pull requests."
    ),
    "antigravity": SkillPresentation(
        name="Antigravity", description="Busca, revisa y modifica archivos con Google Antigravity."
    ),
    "codex": SkillPresentation(
        name="Codex", description="Conversa y crea herramientas para Artemis."
    ),
    "seerr": SkillPresentation(name="Seerr", description="Busca y solicita películas y series."),
    "karakeep": SkillPresentation(name="Karakeep", description="Busca y guarda enlaces."),
    "usenet": SkillPresentation(name="Usenet", description="Busca títulos y gestiona descargas."),
}


def help_target(content: str) -> str | None:
    match = re.fullmatch(r"/?(?:ayuda|help)\s+(.+)", content.strip(), re.IGNORECASE)
    return match.group(1).strip().casefold() if match else None
