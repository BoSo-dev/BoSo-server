from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    policy_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    is_example: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (CheckConstraint("length(policy_key) > 0", name="ck_policies_key"),)


class PolicyVersion(Base):
    __tablename__ = "policy_versions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    policy_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("policies.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    change_summary: Mapped[str] = mapped_column(String(2000), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date)
    reviewed_on: Mapped[date] = mapped_column(Date, nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(100), nullable=False)
    eligibility: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sources: Mapped[list["PolicySource"]] = relationship(order_by="PolicySource.source_key")
    actions: Mapped[list["PolicyAction"]] = relationship(order_by="PolicyAction.action_key")

    __table_args__ = (
        UniqueConstraint("policy_id", "version", name="uq_policy_versions_number"),
        CheckConstraint("version > 0", name="ck_policy_versions_number"),
        CheckConstraint("length(content_hash) = 64", name="ck_policy_versions_hash"),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_policy_versions_period",
        ),
        CheckConstraint("lifecycle IN ('active', 'ended')", name="ck_policy_versions_lifecycle"),
        CheckConstraint(
            "category IN ('transport_card', 'transport_fare', 'transport_support', 'transport_service')",
            name="ck_policy_versions_category",
        ),
        Index("ix_policy_versions_effective", "policy_id", "effective_from", "version"),
    )


class PolicySource(Base):
    __tablename__ = "policy_sources"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False
    )
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(100))
    checked_on: Mapped[date] = mapped_column(Date, nullable=False)
    usage_note: Mapped[str] = mapped_column(String(1000), nullable=False)
    reuse_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)

    __table_args__ = (
        UniqueConstraint("version_id", "source_key", name="uq_policy_sources_key"),
        CheckConstraint(
            "kind IN ('public_api', 'official_page', 'example')", name="ck_policy_sources_kind"
        ),
        CheckConstraint("reuse_confirmed", name="ck_policy_sources_reuse"),
    )


class PolicyAction(Base):
    __tablename__ = "policy_actions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False
    )
    action_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    url: Mapped[str | None] = mapped_column(String(2048))

    __table_args__ = (
        UniqueConstraint("version_id", "action_key", name="uq_policy_actions_key"),
        Index("ix_policy_actions_due_date", "due_date"),
    )
