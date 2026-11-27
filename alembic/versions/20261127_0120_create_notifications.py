"""Create private, deduplicated in-app notifications."""

import sqlalchemy as sa

from alembic import op

revision = "20261127_0120"
down_revision = "20261127_0110"
branch_labels = None
depends_on = None


def upgrade():
    schema = "public" if op.get_bind().dialect.name == "postgresql" else None
    prefix = "public." if schema else ""
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("todo_id", sa.Uuid(), nullable=False),
        sa.Column("event_key", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], [prefix + "users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["todo_id", "user_id"],
            [prefix + "user_todos.id", prefix + "user_todos.user_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "event_key", name="uq_notifications_event"),
        sa.CheckConstraint("kind IN ('new_todo','due_soon')", name="ck_notifications_kind"),
        sa.CheckConstraint("length(event_key)=64", name="ck_notifications_event_key"),
        schema=schema,
    )
    op.create_index(
        "ix_notifications_owner_read_created",
        "notifications",
        ["user_id", "read_at", "created_at"],
        schema=schema,
    )
    if schema:
        op.execute("ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY")
        op.execute("REVOKE ALL PRIVILEGES ON TABLE public.notifications FROM PUBLIC")
        op.execute("""
            DO $block$
            DECLARE client_role text;
            BEGIN
                FOREACH client_role IN ARRAY ARRAY['anon','authenticated','service_role']
                LOOP
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
                        EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.notifications FROM %I',client_role);
                    END IF;
                END LOOP;
            END;
            $block$;
        """)


def downgrade():
    op.drop_table(
        "notifications", schema="public" if op.get_bind().dialect.name == "postgresql" else None
    )
