"""drop project from fuel and maintenance

Revision ID: 8a1f3c7d20b9
Revises: f6b2c8d41e57
Create Date: 2026-10-23

A fill-up and a set of tyres serve whatever the vehicle does next — usually
several jobs in one day — so nobody at the pump can honestly say which
project a fuel record belongs to. The field invited guessing, and a guessed
number in a cost report is worse than none.

Fuel and maintenance are now vehicle costs with no project. Per-project fuel
is derived from trip distance and each vehicle's measured efficiency instead
(see project_service.project_cost_report), which needs no field to be filled
in by hand. Existing values are simply dropped: they were never trustworthy.

Trips and expenses keep their project — a trip genuinely goes to a site, and
a site permit genuinely belongs to one.
"""
import sqlalchemy as sa
from alembic import op

revision = "8a1f3c7d20b9"
down_revision = "f6b2c8d41e57"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("fuel_log") as batch_op:
        batch_op.drop_constraint("fk_fuel_log_project_id", type_="foreignkey")
        batch_op.drop_index("ix_fuel_log_project_id")
        batch_op.drop_column("project_id")

    with op.batch_alter_table("maintenance_log") as batch_op:
        batch_op.drop_constraint("fk_maintenance_log_project_id", type_="foreignkey")
        batch_op.drop_index("ix_maintenance_log_project_id")
        batch_op.drop_column("project_id")


def downgrade():
    with op.batch_alter_table("maintenance_log") as batch_op:
        batch_op.add_column(
            sa.Column("project_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_maintenance_log_project_id",
            "project",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_maintenance_log_project_id", ["project_id"], unique=False
        )

    with op.batch_alter_table("fuel_log") as batch_op:
        batch_op.add_column(
            sa.Column("project_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_fuel_log_project_id",
            "project",
            ["project_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_fuel_log_project_id", ["project_id"], unique=False
        )
