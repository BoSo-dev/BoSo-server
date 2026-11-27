from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ChatSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    gemini_api_key: SecretStr | None = None
    gemini_model: str | None = Field(default=None, pattern=r"^gemini-[a-zA-Z0-9._-]{1,80}$")
    gemini_timeout_seconds: int = Field(default=10, ge=1, le=30)
    gemini_max_output_tokens: int = Field(default=1024, ge=128, le=2048)

    @field_validator("gemini_model", "gemini_api_key", mode="before")
    @classmethod
    def blank_is_missing(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


@lru_cache
def get_chat_settings():
    return ChatSettings()
