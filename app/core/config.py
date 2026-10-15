from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = SecretStr("postgresql+psycopg://boso:boso-local@localhost:5432/boso")
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=0, ge=0, le=20)
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    @model_validator(mode="after")
    def production_settings(self):
        if self.app_env == "production":
            if "*" in self.cors_origins:
                raise ValueError("Production CORS requires explicit origins")
            if not self.database_url.get_secret_value().startswith("postgresql+psycopg://"):
                raise ValueError("Production requires postgresql+psycopg")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
