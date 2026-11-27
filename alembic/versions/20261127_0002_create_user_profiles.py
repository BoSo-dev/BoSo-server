"""Create server-only user transport profiles.

Revision ID: 20261127_0002
Revises: 20261030_0001
"""

import sqlalchemy as sa

from alembic import op

revision = "20261127_0002"
down_revision = "20261030_0001"
branch_labels = None
depends_on = None


def upgrade():
    schema = "public" if op.get_bind().dialect.name == "postgresql" else None
    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("region_code", sa.String(16), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_profiles"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["public.users.id" if schema else "users.id"],
            name="fk_user_profiles_user_id_users",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("birth_date >= '1900-01-01'", name="ck_user_profiles_birth_date_min"),
        sa.CheckConstraint(
            "region_code IN ('seoul', 'busan', 'daegu', 'incheon', 'gwangju', 'daejeon', 'ulsan', 'sejong', 'gyeonggi', 'gangwon', 'chungbuk', 'chungnam', 'jeonbuk', 'jeonnam', 'gyeongbuk', 'gyeongnam', 'jeju')",
            name="ck_user_profiles_region",
        ),
        schema=schema,
    )
    for table, column, size, constraint, fk, choices in (
        (
            "user_transport_cards",
            "card_code",
            32,
            "ck_user_transport_cards_code",
            "fk_user_transport_cards_profile",
            "'k_pass', 'climate_card', 'other_or_none'",
        ),
        (
            "user_transport_modes",
            "mode_code",
            16,
            "ck_user_transport_modes_code",
            "fk_user_transport_modes_profile",
            "'bus', 'subway'",
        ),
    ):
        op.create_table(
            table,
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column(column, sa.String(size), nullable=False),
            sa.PrimaryKeyConstraint("user_id", column, name=f"pk_{table}"),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["public.user_profiles.user_id" if schema else "user_profiles.user_id"],
                name=fk,
                ondelete="CASCADE",
            ),
            sa.CheckConstraint(f"{column} IN ({choices})", name=constraint),
            schema=schema,
        )
    if schema:
        for table in ("user_profiles", "user_transport_cards", "user_transport_modes"):
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
    for table in ("user_transport_modes", "user_transport_cards", "user_profiles"):
        op.drop_table(table, schema=schema)
