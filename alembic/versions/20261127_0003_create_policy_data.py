"""Create reviewed, versioned policy data with server-only access.

Revision ID: 20261127_0003
Revises: 20261127_0002
"""

import sqlalchemy as sa

from alembic import op

revision = "20261127_0003"
down_revision = "20261127_0002"
branch_labels = None
depends_on = None


def upgrade():
    schema = "public" if op.get_bind().dialect.name == "postgresql" else None
    prefix = "public." if schema else ""
    op.create_table(
        "policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_key", sa.String(64), nullable=False),
        sa.Column("is_example", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_key"),
        sa.CheckConstraint("length(policy_key) > 0", name="ck_policies_key"),
        schema=schema,
    )
    op.create_table(
        "policy_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("summary", sa.String(1000), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("change_summary", sa.String(2000), nullable=False),
        sa.Column("lifecycle", sa.String(16), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("reviewed_on", sa.Date(), nullable=False),
        sa.Column("reviewed_by", sa.String(100), nullable=False),
        sa.Column("eligibility", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["policy_id"], [prefix + "policies.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("policy_id", "version", name="uq_policy_versions_number"),
        sa.CheckConstraint("version > 0", name="ck_policy_versions_number"),
        sa.CheckConstraint("length(content_hash) = 64", name="ck_policy_versions_hash"),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_policy_versions_period",
        ),
        sa.CheckConstraint("lifecycle IN ('active', 'ended')", name="ck_policy_versions_lifecycle"),
        sa.CheckConstraint(
            "category IN ('transport_card', 'transport_fare', 'transport_support', 'transport_service')",
            name="ck_policy_versions_category",
        ),
        schema=schema,
    )
    op.create_index(
        "ix_policy_versions_effective",
        "policy_versions",
        ["policy_id", "effective_from", "version"],
        schema=schema,
    )
    op.create_table(
        "policy_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column("checked_on", sa.Date(), nullable=False),
        sa.Column("usage_note", sa.String(1000), nullable=False),
        sa.Column("reuse_confirmed", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["version_id"], [prefix + "policy_versions.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("version_id", "source_key", name="uq_policy_sources_key"),
        sa.CheckConstraint(
            "kind IN ('public_api', 'official_page', 'example')", name="ck_policy_sources_kind"
        ),
        sa.CheckConstraint("reuse_confirmed", name="ck_policy_sources_reuse"),
        schema=schema,
    )
    op.create_table(
        "policy_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("action_key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["version_id"], [prefix + "policy_versions.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("version_id", "action_key", name="uq_policy_actions_key"),
        schema=schema,
    )
    op.create_index("ix_policy_actions_due_date", "policy_actions", ["due_date"], schema=schema)
    if schema:
        for table in ("policies", "policy_versions", "policy_sources", "policy_actions"):
            op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
            op.execute(f'REVOKE ALL PRIVILEGES ON TABLE public."{table}" FROM PUBLIC')
            op.execute(f"""
                DO $block$
                DECLARE client_role text;
                BEGIN
                    FOREACH client_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
                    LOOP
                        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = client_role) THEN
                            EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE public.%I FROM %I', '{table}', client_role);
                        END IF;
                    END LOOP;
                END;
                $block$;
            """)


def downgrade():
    schema = "public" if op.get_bind().dialect.name == "postgresql" else None
    for table in ("policy_actions", "policy_sources", "policy_versions", "policies"):
        op.drop_table(table, schema=schema)
