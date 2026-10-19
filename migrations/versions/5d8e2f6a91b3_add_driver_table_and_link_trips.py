"""add driver table and link trips to it

Revision ID: 5d8e2f6a91b3
Revises: 2c6bebe5e8c0
Create Date: 2026-10-11 12:40:00.000000

Drivers replace free-typed driver names. ``trip_log.driver_id`` links a trip to
its registered driver; ``trip_log.driver_name`` stays as a denormalised snapshot
so history survives a driver being renamed or deleted (hence ON DELETE SET NULL,
not CASCADE).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5d8e2f6a91b3'
down_revision = '2c6bebe5e8c0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('driver',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('license_number', sa.String(length=40), nullable=True),
    sa.Column('card_code', sa.String(length=30), nullable=False),
    sa.Column('card_status', sa.Enum('active', 'lost', 'expired', name='driver_card_status'), nullable=True),
    sa.Column('status', sa.Enum('active', 'inactive', 'suspended', name='driver_status'), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('driver', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_driver_card_code'), ['card_code'], unique=True)
        batch_op.create_index(batch_op.f('ix_driver_card_status'), ['card_status'], unique=False)
        batch_op.create_index(batch_op.f('ix_driver_name'), ['name'], unique=False)
        batch_op.create_index(batch_op.f('ix_driver_status'), ['status'], unique=False)

    # SQLite cannot ALTER TABLE ... ADD CONSTRAINT, so batch mode recreates
    # trip_log. copy_from pins the full target shape — without it the recreate
    # would silently drop the ck_trip_time CHECK and the vehicle CASCADE FK,
    # because SQLite's reflection does not report CHECK constraints.
    trip_log = sa.Table(
        'trip_log',
        sa.MetaData(),
        sa.Column('vehicle_id', sa.Integer(), nullable=False),
        sa.Column('driver_name', sa.String(length=120), nullable=False),
        sa.Column('purpose', sa.String(length=200), nullable=False),
        sa.Column('origin', sa.String(length=160), nullable=False),
        sa.Column('destination', sa.String(length=160), nullable=False),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('distance_km', sa.Float(), nullable=True),
        sa.Column('odometer_start', sa.Float(), nullable=True),
        sa.Column('odometer_end', sa.Float(), nullable=True),
        sa.Column('status', sa.Enum('planned', 'in_progress', 'completed', 'cancelled', name='trip_status'), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('end_time IS NULL OR end_time >= start_time', name='ck_trip_time'),
        sa.ForeignKeyConstraint(['vehicle_id'], ['vehicle.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('trip_log', schema=None, copy_from=trip_log) as batch_op:
        batch_op.add_column(sa.Column('driver_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_trip_log_driver_id'), ['driver_id'], unique=False)
        batch_op.create_foreign_key('fk_trip_log_driver_id', 'driver', ['driver_id'], ['id'], ondelete='SET NULL')


def downgrade():
    # Reverse the recreate: drop the driver link, restoring the original shape.
    trip_log = sa.Table(
        'trip_log',
        sa.MetaData(),
        sa.Column('vehicle_id', sa.Integer(), nullable=False),
        sa.Column('driver_name', sa.String(length=120), nullable=False),
        sa.Column('purpose', sa.String(length=200), nullable=False),
        sa.Column('origin', sa.String(length=160), nullable=False),
        sa.Column('destination', sa.String(length=160), nullable=False),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('distance_km', sa.Float(), nullable=True),
        sa.Column('odometer_start', sa.Float(), nullable=True),
        sa.Column('odometer_end', sa.Float(), nullable=True),
        sa.Column('status', sa.Enum('planned', 'in_progress', 'completed', 'cancelled', name='trip_status'), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint('end_time IS NULL OR end_time >= start_time', name='ck_trip_time'),
        sa.ForeignKeyConstraint(['vehicle_id'], ['vehicle.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('trip_log', schema=None, copy_from=trip_log) as batch_op:
        batch_op.drop_constraint('fk_trip_log_driver_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_trip_log_driver_id'))
        batch_op.drop_column('driver_id')

    with op.batch_alter_table('driver', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_driver_status'))
        batch_op.drop_index(batch_op.f('ix_driver_name'))
        batch_op.drop_index(batch_op.f('ix_driver_card_status'))
        batch_op.drop_index(batch_op.f('ix_driver_card_code'))

    op.drop_table('driver')
