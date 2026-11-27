from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.modules.policies.models import PolicyAction


class UserTodo(Base):
    __tablename__ = "user_todos"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    policy_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("policies.id", ondelete="RESTRICT"), nullable=False
    )
    action_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("policy_actions.id", ondelete="RESTRICT"), nullable=False
    )
    action_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    archived_reason: Mapped[str | None] = mapped_column(String(32))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    action: Mapped[PolicyAction] = relationship(lazy="selectin")

    __table_args__ = (
        UniqueConstraint("user_id", "policy_id", "action_key", name="uq_user_todos_action"),
        UniqueConstraint("id", "user_id", name="uq_user_todos_id_owner"),
        CheckConstraint(
            "status IN ('pending','completed','archived')", name="ck_user_todos_status"
        ),
        CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) OR (status <> 'completed' AND completed_at IS NULL)",
            name="ck_user_todos_completion",
        ),
        CheckConstraint(
            "(status = 'archived' AND archived_reason IS NOT NULL) OR (status <> 'archived' AND archived_reason IS NULL)",
            name="ck_user_todos_archive",
        ),
        Index("ix_user_todos_owner_status_due", "user_id", "status", "due_date"),
    )
