from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.database_url import resolve_database_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr = SecretStr("postgresql+psycopg://boso:boso-local@localhost:5432/boso")
    migration_database_url: SecretStr | None = None
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_max_overflow: int = Field(default=0, ge=0, le=20)
    db_connect_timeout: int = Field(default=5, ge=1, le=60)
    db_pool_timeout: int = Field(default=10, ge=1, le=60)
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    @model_validator(mode="after")
    def production_settings(self):
        runtime_url = resolve_database_url(self.database_url.get_secret_value())
        if self.migration_database_url is not None:
            resolve_database_url(self.migration_database_url.get_secret_value(), migration=True)
        if self.app_env == "production":
            if "*" in self.cors_origins:
                raise ValueError("Production CORS requires explicit origins")
            if runtime_url.drivername != "postgresql+psycopg":
                raise ValueError("Production requires postgresql+psycopg")
        return self

    def get_database_url(self, *, migration: bool = False):
        value = self.migration_database_url if migration else None
        return resolve_database_url(
            (value or self.database_url).get_secret_value(), migration=migration
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
