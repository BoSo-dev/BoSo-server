from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

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
    auth_jwt_key: SecretStr | None = None
    auth_csrf_key: SecretStr | None = None
    auth_jwt_issuer: str = "boso-api"
    auth_jwt_audience: str = "boso-web"

    @model_validator(mode="after")
    def production_settings(self):
        for origin in self.cors_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
                or "*" in origin
            ):
                raise ValueError("CORS requires exact HTTP(S) origins without paths")
            if self.app_env == "production" and parsed.scheme != "https":
                raise ValueError("Production CORS requires HTTPS origins")
        keys = [self.auth_jwt_key, self.auth_csrf_key]
        if any(key is not None and len(key.get_secret_value().encode()) < 32 for key in keys):
            raise ValueError("Authentication keys must each contain at least 32 bytes")
        if all(keys) and keys[0].get_secret_value() == keys[1].get_secret_value():
            raise ValueError("JWT and CSRF keys must be different")
        if self.app_env == "production" and not all(keys):
            raise ValueError("Production requires separate JWT and CSRF keys")
        if not self.auth_jwt_issuer or not self.auth_jwt_audience:
            raise ValueError("JWT issuer and audience must not be empty")
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
