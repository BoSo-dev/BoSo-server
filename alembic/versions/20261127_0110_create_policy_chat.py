"""Create private policy conversations and idempotent turns."""

import sqlalchemy as sa

from alembic import op

revision = "20261127_0110"
down_revision = "20261127_0100"
branch_labels = None
depends_on = None


def upgrade():
    schema = "public" if op.get_bind().dialect.name == "postgresql" else None
    prefix = "public." if schema else ""
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], [prefix + "users.id"], ondelete="CASCADE"),
        schema=schema,
    )
    op.create_index(
        "ix_chat_conversations_owner_updated",
        "chat_conversations",
        ["user_id", "updated_at"],
        schema=schema,
    )
    op.create_table(
        "chat_turns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("question", sa.String(2000), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("needs_more_info", sa.Boolean(), nullable=False),
        sa.Column("external_used", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], [prefix + "chat_conversations.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("conversation_id", "request_id", name="uq_chat_turns_request"),
        sa.UniqueConstraint("conversation_id", "turn_number", name="uq_chat_turns_number"),
        sa.CheckConstraint("length(request_hash)=64", name="ck_chat_turns_hash"),
        sa.CheckConstraint("turn_number > 0", name="ck_chat_turns_number"),
        schema=schema,
    )
    if schema:
        for table in ("chat_conversations", "chat_turns"):
            op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'REVOKE ALL PRIVILEGES ON TABLE public."{table}" FROM PUBLIC')
            op.execute(f"""
                DO $block$
                DECLARE client_role text;
                BEGIN
                    FOREACH client_role IN ARRAY ARRAY['anon','authenticated','service_role']
                    LOOP
                        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=client_role) THEN
                            EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.%I FROM %I','{table}',client_role);
                        END IF;
                    END LOOP;
                END;
                $block$;
            """)


def downgrade():
    schema = "public" if op.get_bind().dialect.name == "postgresql" else None
    op.drop_table("chat_turns", schema=schema)
    op.drop_table("chat_conversations", schema=schema)
