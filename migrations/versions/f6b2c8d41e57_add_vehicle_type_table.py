"""add vehicle_type registry table (user-managed type list)

Revision ID: f6b2c8d41e57
Revises: d4e8f2a61c93
Create Date: 2026-10-20

Vehicle types become a managed registry: users add/delete them on the
Vehicles -> Vehicle Types subtab, and the vehicle form's Type dropdown is
built from these rows. Every type already in use is registered here during
the upgrade so existing vehicles keep their value selectable on edit.
"""
import sqlalchemy as sa
from alembic import op

revision = "f6b2c8d41e57"
down_revision = "d4e8f2a61c93"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vehicle_type",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_vehicle_type_name"), "vehicle_type", ["name"], unique=True
    )
    # Backfill: register every type the current fleet already uses, so those
    # values stay selectable in the Type dropdown after the upgrade.
    op.execute(
        sa.text(
            """
            INSERT INTO vehicle_type (name, created_at, updated_at)
            SELECT DISTINCT vehicle_type, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM vehicle
            WHERE vehicle_type IS NOT NULL AND vehicle_type != ''
            """
        )
    )


def downgrade():
    op.drop_index(op.f("ix_vehicle_type_name"), table_name="vehicle_type")
    op.drop_table("vehicle_type")
