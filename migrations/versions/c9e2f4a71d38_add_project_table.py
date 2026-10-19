"""add project table and optional project links on cost records

Revision ID: c9e2f4a71d38
Revises: b3f1d70c4a62
Create Date: 2026-10-19 12:00:00.000000

A construction job/site that fuel, trips, maintenance and expenses can be
booked to, so per-project cost reports become possible. All four links are
nullable (office costs and quick entries belong to no job) and ON DELETE
SET NULL — deleting a project must not erase money that was actually spent,
mirroring expense.vehicle_id.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9e2f4a71d38'
down_revision = 'b3f1d70c4a62'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('project',
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('code', sa.String(length=30), nullable=False),
    sa.Column('client', sa.String(length=150), nullable=True),
    sa.Column('location', sa.String(length=200), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('status', sa.Enum('planned', 'active', 'on_hold', 'completed', 'cancelled', name='project_status'), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('end_date IS NULL OR start_date IS NULL OR end_date >= start_date', name='ck_project_dates'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('project', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_project_code'), ['code'], unique=True)
        batch_op.create_index(batch_op.f('ix_project_name'), ['name'], unique=False)
        batch_op.create_index(batch_op.f('ix_project_status'), ['status'], unique=False)

    for table in ('trip_log', 'fuel_log', 'maintenance_log', 'expense'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(sa.Column('project_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                f'fk_{table}_project_id', 'project', ['project_id'], ['id'], ondelete='SET NULL'
            )
            batch_op.create_index(batch_op.f(f'ix_{table}_project_id'), ['project_id'], unique=False)


def downgrade():
    for table in ('expense', 'maintenance_log', 'fuel_log', 'trip_log'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(batch_op.f(f'ix_{table}_project_id'))
            batch_op.drop_constraint(f'fk_{table}_project_id', type_='foreignkey')
            batch_op.drop_column('project_id')

    with op.batch_alter_table('project', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_project_status'))
        batch_op.drop_index(batch_op.f('ix_project_name'))
        batch_op.drop_index(batch_op.f('ix_project_code'))

    op.drop_table('project')
