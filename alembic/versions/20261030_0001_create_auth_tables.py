"""Create server-only authentication tables.

Revision ID: 20261030_0001
Revises: None
"""

import sqlalchemy as sa

from alembic import op

revision: str = "20261030_0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def _schema() -> str | None:
    return "public" if op.get_bind().dialect.name == "postgresql" else None


def upgrade() -> None:
    schema = _schema()
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.CheckConstraint(
            "length(email) > 0 AND email = trim(email)", name="ck_users_email_trimmed"
        ),
        sa.CheckConstraint("length(password_hash) > 0", name="ck_users_password_hash_not_empty"),
        schema=schema,
    )
    op.create_index(
        "uq_users_email_ci", "users", [sa.text("lower(email)")], unique=True, schema=schema
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(32), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["public.users.id" if schema else "users.id"],
            name="fk_auth_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_auth_sessions_expiry"),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name="ck_auth_sessions_revoked_at"
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revocation_reason IS NULL) OR "
            "(revoked_at IS NOT NULL AND revocation_reason IS NOT NULL AND "
            "revocation_reason IN ('logout', 'refresh_reuse', 'user_disabled'))",
            name="ck_auth_sessions_revocation_state",
        ),
        schema=schema,
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"], schema=schema)
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"], schema=schema)
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["public.auth_sessions.id" if schema else "auth_sessions.id"],
            name="fk_refresh_tokens_session_id_auth_sessions",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
        sa.CheckConstraint("length(token_hash) = 64", name="ck_refresh_tokens_hash_length"),
        sa.CheckConstraint("expires_at > created_at", name="ck_refresh_tokens_expiry"),
        sa.CheckConstraint(
            "used_at IS NULL OR used_at >= created_at", name="ck_refresh_tokens_used_at"
        ),
        schema=schema,
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"], schema=schema)
    op.create_index(
        "uq_refresh_tokens_unconsumed_session",
        "refresh_tokens",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("used_at IS NULL"),
        sqlite_where=sa.text("used_at IS NULL"),
        schema=schema,
    )

    if schema:
        # No policies: non-owner, non-BYPASSRLS roles are denied by default.
        # Revoke ACLs too: RLS does not cover TRUNCATE or BYPASSRLS roles.
        for table in ("users", "auth_sessions", "refresh_tokens"):
            op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'REVOKE ALL PRIVILEGES ON TABLE public."{table}" FROM PUBLIC')
            # Ordinary PostgreSQL need not have Supabase's Data API roles.
            # Table/role identifiers here are fixed constants, never user input.
            op.execute(f"""
                DO $block$
                DECLARE client_role text;
                BEGIN
                    FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
                    LOOP
                        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
                            EXECUTE format(
                                'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM %I',
                                '{table}', client_role
                            );
                        END IF;
                    END LOOP;
                END;
                $block$;
            """)


def downgrade() -> None:
    # Dropping children first also removes only these tables' indexes/policies.
    schema = _schema()
    op.drop_table("refresh_tokens", schema=schema)
    op.drop_table("auth_sessions", schema=schema)
    op.drop_table("users", schema=schema)
