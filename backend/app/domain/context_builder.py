"""Versioned settings and transport envelopes for the Rust context engine."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PersonaPolicy = Literal["CORE_ONLY", "CORE_PLUS_RELEVANT_EXTENDED", "FULL_PERSONA", "ADAPTIVE"]
Component = Literal["core", "extended", "history", "summary", "memory", "tools",
                    "operations", "additional"]


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: int = Field(ge=0, le=254)
    minimum: int = Field(default=0, ge=0, le=32000)
    maximum: int = Field(ge=1, le=32000)
    enabled: bool = True
    compression: Literal["select", "omit"] = "select"
    recovery: Literal["relevant", "always", "never"] = "relevant"

    @model_validator(mode="after")
    def limits(self):
        if self.minimum > self.maximum:
            raise ValueError("El mínimo supera el máximo.")
        return self


def default_components() -> dict[Component, Policy]:
    return {
        "core": Policy(priority=254, maximum=200),
        "operations": Policy(priority=254, maximum=16000),
        "history": Policy(priority=180, maximum=2200),
        "tools": Policy(priority=190, maximum=6000),
        "summary": Policy(priority=140, maximum=800),
        "memory": Policy(priority=130, maximum=1000),
        "extended": Policy(priority=120, maximum=1200),
        "additional": Policy(priority=170, maximum=1800),
    }


class ContextSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    mode: Literal["conservador", "equilibrado", "agresivo", "personalizado"] = "equilibrado"
    budget: int = Field(default=12000, ge=1024, le=64000)
    response_reserve: int = Field(default=1600, ge=128, le=32000)
    tool_reserve: int = Field(default=1000, ge=0, le=16000)
    safety_margin: int = Field(default=500, ge=128, le=16000)
    fallback: Literal["legacy", "basic"] = "legacy"
    metrics: bool = True
    cache: bool = True
    persona_policy: PersonaPolicy = "ADAPTIVE"
    recent_turns: int = Field(default=8, ge=2, le=20)
    summarize_after: int = Field(default=14, ge=2, le=100)
    summary_size: int = Field(default=2400, ge=200, le=8000)
    semantic_memory: bool = True
    max_memories: int = Field(default=4, ge=0, le=20)
    memory_threshold: float = Field(default=0.35, ge=0, le=1)
    memory_recency: float = Field(default=0.15, ge=0, le=1)
    deduplicate: bool = True
    adaptive_calibration: bool = True
    dynamic_tools: bool = False
    include_dependencies: bool = True
    max_tools: int = Field(default=5, ge=1, le=40)
    tool_threshold: int = Field(default=1, ge=0, le=12)
    full_catalog_fallback: bool = True
    bytes_per_token: int = Field(default=3, ge=1, le=8)
    input_price_per_million: float | None = Field(default=None, ge=0, le=10000)
    output_price_per_million: float | None = Field(default=None, ge=0, le=10000)
    components: dict[Component, Policy] = Field(default_factory=default_components)

    @model_validator(mode="after")
    def limits(self):
        if self.budget - self.response_reserve - self.tool_reserve - self.safety_margin < 512:
            raise ValueError("Las reservas deben dejar al menos 512 tokens de entrada.")
        if self.components.keys() != default_components().keys():
            raise ValueError("Faltan componentes de contexto.")
        for name in ("core", "operations"):
            policy = self.components[name]
            if not policy.enabled or policy.recovery == "never" or policy.priority != 254:
                raise ValueError("La identidad y el estado de operaciones son obligatorios.")
        return self

    def runtime(self) -> dict:
        data = self.model_dump()
        if self.mode == "agresivo":
            data["max_tools"] = min(self.max_tools, 3)
            data["components"]["history"]["maximum"] = min(
                self.components["history"].maximum, 1300,
            )
        if self.mode == "conservador":
            data["dynamic_tools"] = False
        return data


def merge_settings(*layers: dict) -> ContextSettings:
    result = ContextSettings().model_dump()
    for layer in layers:
        for key, value in layer.items():
            if key == "components":
                for name, policy in value.items():
                    result[key][name] = {**result[key].get(name, {}), **policy}
            else:
                result[key] = value
    return ContextSettings.model_validate(result)


class ContextInput(BaseModel):
    version: Literal[1] = 1
    instructions: str
    core: str
    extended: str
    greeting: str
    message: str
    image_context: str
    history: list[dict]
    summary: dict | None
    memories: list[str]
    skills: list[dict[str, str]]
    observations: list[dict[str, str]]
    approvals: list[dict[str, str]]
    actions_remaining: int
    settings: dict[str, dict]
