"""vehicle type becomes free-form user text instead of a fixed enum

Revision ID: d4e8f2a61c93
Revises: c9e2f4a71d38
Create Date: 2026-10-20

The vehicle_type column was a fixed ENUM checked by the database, so fleets
could only ever use the seven baked-in names. Users name their machines their
own way ("Tipper", "Grader", "Water Tanker"), so the column becomes plain
VARCHAR(50). Existing rows keep their current values — they're valid text.
"""
import sqlalchemy as sa
from alembic import op

revision = "d4e8f2a61c93"
down_revision = "c9e2f4a71d38"
branch_labels = None
depends_on = None

_OLD_ENUM = sa.Enum(
    "excavator", "dump_truck", "loader", "bulldozer", "crane",
    "concrete_mixer", "other", name="vehicle_type",
)


def upgrade():
    # SQLite cannot alter a column in place; batch mode rebuilds the table,
    # which also drops the CHECK constraint that pinned types to the enum.
    with op.batch_alter_table("vehicle", recreate="always") as batch_op:
        batch_op.alter_column(
            "vehicle_type",
            existing_type=_OLD_ENUM,
            existing_nullable=True,
            type_=sa.String(length=50),
        )


def downgrade():
    # WARNING: types invented since the upgrade that aren't in the old enum
    # will fail to convert back.
    with op.batch_alter_table("vehicle", recreate="always") as batch_op:
        batch_op.alter_column(
            "vehicle_type",
            existing_type=sa.String(length=50),
            existing_nullable=True,
            type_=_OLD_ENUM,
        )
