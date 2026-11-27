from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(max_length=320)
    password: SecretStr = Field(min_length=15, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str = Field(repr=False)
    token_type: str = "bearer"
    expires_in: int
    session_expires_at: datetime
    csrf_token: str = Field(repr=False)


class CsrfResponse(BaseModel):
    csrf_token: str = Field(repr=False)
