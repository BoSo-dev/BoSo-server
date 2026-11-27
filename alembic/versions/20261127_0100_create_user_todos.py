"""Create owner-scoped, version-backed todos."""

import sqlalchemy as sa

from alembic import op

revision = "20261127_0100"
down_revision = "20261127_0003"
branch_labels = None
depends_on = None


def upgrade():
    schema = "public" if op.get_bind().dialect.name == "postgresql" else None
    prefix = "public." if schema else ""
    op.create_table(
        "user_todos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("action_key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("archived_reason", sa.String(32), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], [prefix + "users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_id"], [prefix + "policies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["action_id"], [prefix + "policy_actions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("user_id", "policy_id", "action_key", name="uq_user_todos_action"),
        sa.UniqueConstraint("id", "user_id", name="uq_user_todos_id_owner"),
        sa.CheckConstraint(
            "status IN ('pending','completed','archived')", name="ck_user_todos_status"
        ),
        sa.CheckConstraint(
            "(status = 'completed' AND completed_at IS NOT NULL) OR (status <> 'completed' AND completed_at IS NULL)",
            name="ck_user_todos_completion",
        ),
        sa.CheckConstraint(
            "(status = 'archived' AND archived_reason IS NOT NULL) OR (status <> 'archived' AND archived_reason IS NULL)",
            name="ck_user_todos_archive",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_user_todos_owner_status_due",
        "user_todos",
        ["user_id", "status", "due_date"],
        schema=schema,
    )
    if schema:
        op.execute("ALTER TABLE public.user_todos ENABLE ROW LEVEL SECURITY")
        op.execute("REVOKE ALL PRIVILEGES ON TABLE public.user_todos FROM PUBLIC")
        op.execute("""
            DO $block$
            DECLARE client_role text;
            BEGIN
                FOREACH client_role IN ARRAY ARRAY['anon','authenticated','service_role']
                LOOP
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
                        EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.user_todos FROM %I', client_role);
                    END IF;
                END LOOP;
            END;
            $block$;
        """)


def downgrade():
    op.drop_table(
        "user_todos", schema="public" if op.get_bind().dialect.name == "postgresql" else None
    )
