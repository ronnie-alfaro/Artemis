from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr

Provider = Literal["whatsapp", "telegram"]


class ChannelConnection(BaseModel):
    enabled: bool = True
    token: SecretStr
    agent_name: str = Field(default="primary", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    allowed_user_ids: list[int] = Field(default_factory=list)

    def validate_for(self, provider: Provider) -> None:
        token = self.token.get_secret_value()
        if not token or any(char.isspace() for char in token):
            raise ValueError("Introduce un token válido.")
        if provider == "telegram":
            bot_id, separator, secret = token.partition(":")
            if not separator or not bot_id.isdigit() or not secret:
                raise ValueError("Introduce un token válido de Telegram.")
            if not self.allowed_user_ids or any(value <= 0 for value in self.allowed_user_ids):
                raise ValueError(
                    "Introduce al menos un identificador numérico de usuario autorizado."
                )
            self.agent_name = bot_id


class ChannelConfigurationInput(BaseModel):
    enabled: bool = True
    token: SecretStr | None = None
    agent_name: str = Field(default="primary", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    allowed_user_ids: list[int] = Field(default_factory=list)


class ChannelConfigurationStatus(BaseModel):
    configured: bool
    enabled: bool = False
    editable: bool
    credential_source: str | None = None
    agent_name: str | None = None
    allowed_user_ids: list[int] = Field(default_factory=list)
