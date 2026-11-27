from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.users.constants import RegionCode, TransportCard, TransportMode


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    birth_date: date | None = None
    region_code: RegionCode | None = None
    transport_cards: list[TransportCard] = Field(default_factory=list, max_length=3)
    transport_modes: list[TransportMode] = Field(default_factory=list, max_length=2)

    @field_validator("birth_date", mode="before")
    @classmethod
    def iso_date_only(cls, value):
        # Reject timestamps/numeric epochs even though Pydantic date can coerce them.
        if value is not None and (
            not isinstance(value, str)
            or len(value) != 10
            or value[4] != "-"
            or value[7] != "-"
            or not (value[:4] + value[5:7] + value[8:]).isascii()
            or not (value[:4] + value[5:7] + value[8:]).isdigit()
        ):
            raise ValueError("birth_date must use YYYY-MM-DD")
        return value

    @field_validator("transport_cards", "transport_modes")
    @classmethod
    def no_duplicates(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Duplicate selections are not allowed")
        return value

    @model_validator(mode="after")
    def valid_patch(self):
        if not self.model_fields_set:
            raise ValueError("At least one profile field is required")
        if "other_or_none" in self.transport_cards and len(self.transport_cards) > 1:
            raise ValueError("other_or_none cannot be combined with named cards")
        return self


class PersonalizationContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID
    reference_date: date
    age: int | None
    region_code: RegionCode | None
    transport_cards: list[TransportCard]
    transport_modes: list[TransportMode]
    is_complete: bool
    missing_fields: list[str]


class ProfileResponse(PersonalizationContext):
    email: str
    birth_date: date | None
    updated_at: datetime | None


class Choice(BaseModel):
    code: str
    label: str


class ProfileOptions(BaseModel):
    regions: list[Choice]
    transport_cards: list[Choice]
    transport_modes: list[Choice]
