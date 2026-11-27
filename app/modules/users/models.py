from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.modules.users.constants import REGION_CODES, TRANSPORT_CARDS, TRANSPORT_MODES


def allowed_values(column: str, values: tuple[str, ...]):
    # Only application constants, never request values, are interpolated here.
    return column + " IN (" + ", ".join(f"'{value}'" for value in values) + ")"


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", name="fk_user_profiles_user_id_users", ondelete="CASCADE"),
        primary_key=True,
    )
    birth_date: Mapped[date | None] = mapped_column(Date)
    region_code: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    cards: Mapped[list["UserTransportCard"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )
    modes: Mapped[list["UserTransportMode"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        PrimaryKeyConstraint("user_id", name="pk_user_profiles"),
        CheckConstraint("birth_date >= '1900-01-01'", name="ck_user_profiles_birth_date_min"),
        CheckConstraint(
            allowed_values("region_code", REGION_CODES), name="ck_user_profiles_region"
        ),
    )


class UserTransportCard(Base):
    __tablename__ = "user_transport_cards"

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "user_profiles.user_id", name="fk_user_transport_cards_profile", ondelete="CASCADE"
        ),
        primary_key=True,
    )
    card_code: Mapped[str] = mapped_column(String(32), primary_key=True)

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "card_code", name="pk_user_transport_cards"),
        CheckConstraint(
            allowed_values("card_code", TRANSPORT_CARDS), name="ck_user_transport_cards_code"
        ),
    )


class UserTransportMode(Base):
    __tablename__ = "user_transport_modes"

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "user_profiles.user_id", name="fk_user_transport_modes_profile", ondelete="CASCADE"
        ),
        primary_key=True,
    )
    mode_code: Mapped[str] = mapped_column(String(16), primary_key=True)

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "mode_code", name="pk_user_transport_modes"),
        CheckConstraint(
            allowed_values("mode_code", TRANSPORT_MODES), name="ck_user_transport_modes_code"
        ),
    )
