"""add expense table for non-fuel, non-maintenance costs

Revision ID: 7a4c8e21f905
Revises: 5d8e2f6a91b3
Create Date: 2026-10-11 15:20:00.000000

Insurance, registration, wages, parking, tolls, washing, fines, office
overhead and parts. Fuel and maintenance keep their own specialised logs.

vehicle_id is nullable (fleet-wide costs) and ON DELETE SET NULL — deleting a
vehicle must not erase money that was actually spent.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7a4c8e21f905'
down_revision = '5d8e2f6a91b3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('expense',
    sa.Column('vehicle_id', sa.Integer(), nullable=True),
    sa.Column('expense_date', sa.Date(), nullable=False),
    sa.Column('category', sa.Enum('insurance', 'registration', 'wages', 'parking', 'toll', 'washing', 'fine', 'office', 'parts', 'other', name='expense_category'), nullable=True),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('amount', sa.Float(), nullable=False),
    sa.Column('vendor', sa.String(length=120), nullable=True),
    sa.Column('payment_method', sa.String(length=40), nullable=True),
    sa.Column('receipt_ref', sa.String(length=80), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('amount >= 0', name='ck_expense_amount'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicle.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('expense', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_expense_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_expense_expense_date'), ['expense_date'], unique=False)
        batch_op.create_index(batch_op.f('ix_expense_vehicle_id'), ['vehicle_id'], unique=False)


def downgrade():
    with op.batch_alter_table('expense', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_expense_vehicle_id'))
        batch_op.drop_index(batch_op.f('ix_expense_expense_date'))
        batch_op.drop_index(batch_op.f('ix_expense_category'))

    op.drop_table('expense')
