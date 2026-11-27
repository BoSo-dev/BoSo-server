from datetime import date
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from app.modules.users.constants import RegionCode, TransportCard, TransportMode

Key = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Text = Annotated[str, Field(min_length=1, max_length=10000)]
Category = Literal["transport_card", "transport_fare", "transport_support", "transport_service"]


def iso_date(value):
    if type(value) is date:
        return value
    if (
        not isinstance(value, str)
        or len(value) != 10
        or value[4] != "-"
        or value[7] != "-"
        or not (value[:4] + value[5:7] + value[8:]).isascii()
        or not (value[:4] + value[5:7] + value[8:]).isdigit()
    ):
        raise ValueError("Dates must use YYYY-MM-DD")
    return value


IsoDate = Annotated[date, BeforeValidator(iso_date)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)


def public_url(value: str):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        raise ValueError("Use a public HTTPS URL without credentials, query or fragment")
    return value


class EligibilityRules(StrictModel):
    age_min: int | None = Field(default=None, ge=0, le=150, strict=True)
    age_max: int | None = Field(default=None, ge=0, le=150, strict=True)
    region_codes: list[RegionCode] = Field(default_factory=list, max_length=17)
    transport_cards: list[TransportCard] = Field(default_factory=list, max_length=3)
    transport_modes: list[TransportMode] = Field(default_factory=list, max_length=2)
    additional_requirements: list[Text] = Field(default_factory=list, max_length=20)
    requires_confirmation: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def valid_conditions(self):
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("age_min must not exceed age_max")
        for values in (self.region_codes, self.transport_cards, self.transport_modes):
            if len(values) != len(set(values)):
                raise ValueError("Duplicate conditions are not allowed")
            values.sort()
        if "other_or_none" in self.transport_cards:
            raise ValueError("other_or_none cannot establish policy eligibility")
        if self.additional_requirements and not self.requires_confirmation:
            raise ValueError("Additional requirements need confirmation")
        if "climate_card" in self.transport_cards and not self.requires_confirmation:
            raise ValueError("The profile card code cannot establish a specific card product")
        return self


class PolicySourceInput(StrictModel):
    source_key: Key
    kind: Literal["public_api", "official_page", "example"]
    url: str = Field(min_length=1, max_length=2048)
    title: str = Field(min_length=1, max_length=200)
    external_id: str | None = Field(default=None, min_length=1, max_length=100)
    checked_on: IsoDate
    usage_note: str = Field(min_length=1, max_length=1000)
    reuse_confirmed: bool = Field(strict=True)

    _url = field_validator("url")(public_url)


class PolicyActionInput(StrictModel):
    action_key: Key
    title: str = Field(min_length=1, max_length=200)
    description: Text
    due_date: IsoDate | None = None
    url: str | None = Field(default=None, max_length=2048)

    @field_validator("url")
    @classmethod
    def action_url(cls, value):
        return public_url(value) if value is not None else None


class PolicyVersionInput(StrictModel):
    policy_key: Key
    is_example: bool = Field(strict=True)
    version: int = Field(ge=1, strict=True)
    title: str = Field(min_length=1, max_length=200)
    category: Category
    summary: str = Field(min_length=1, max_length=1000)
    content: Text
    change_summary: str = Field(min_length=1, max_length=2000)
    lifecycle: Literal["active", "ended"]
    effective_from: IsoDate
    effective_until: IsoDate | None = None
    reviewed_on: IsoDate
    reviewed_by: str = Field(min_length=1, max_length=100)
    eligibility: EligibilityRules
    sources: list[PolicySourceInput] = Field(min_length=1, max_length=10)
    actions: list[PolicyActionInput] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def valid_version(self):
        if self.effective_until is not None and self.effective_until < self.effective_from:
            raise ValueError("Invalid effective period")
        if self.lifecycle == "ended" and self.actions:
            raise ValueError("Ended versions cannot introduce actions")
        for rows, attribute in ((self.sources, "source_key"), (self.actions, "action_key")):
            if len(rows) != len({getattr(row, attribute) for row in rows}):
                raise ValueError("Duplicate source or action keys")
            rows.sort(key=lambda row: getattr(row, attribute))
        for source in self.sources:
            if source.checked_on > self.reviewed_on:
                raise ValueError("Review must follow source checks")
            if (source.kind == "example") != self.is_example:
                raise ValueError("Example and real sources must not be mixed")
            if not source.reuse_confirmed:
                raise ValueError("Source reuse must be checked before registration")
        return self


class PolicyImportFile(StrictModel):
    schema_version: Literal[1]
    policies: list[PolicyVersionInput] = Field(min_length=1, max_length=100)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_schema_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value

    @model_validator(mode="after")
    def unique_policies(self):
        if len(self.policies) != len({policy.policy_key for policy in self.policies}):
            raise ValueError("One version per policy per file is allowed")
        return self


class PolicyActionSnapshot(PolicyActionInput):
    id: UUID


class PolicySnapshot(PolicyVersionInput):
    policy_id: UUID
    version_id: UUID
    reference_date: date
    state: Literal["active", "ended", "expired"]
    actions: list[PolicyActionSnapshot]
