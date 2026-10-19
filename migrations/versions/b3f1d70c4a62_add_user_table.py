"""add user table for login accounts

Revision ID: b3f1d70c4a62
Revises: 7a4c8e21f905
Create Date: 2026-10-13 09:40:00.000000

Accounts for the authenticated deployment: username, scrypt password hash,
role (admin/operator/viewer), active flag and last-login timestamp.

UNIQUE index on username is case-insensitive in spirit but expressed the same
way as create_all() (unique=True) so `flask db upgrade` and `db.create_all()`
produce identical schema. Lookups that must ignore case go through
auth_service.find_by_username(), which uses ILIKE.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b3f1d70c4a62'
down_revision = '7a4c8e21f905'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user',
        sa.Column('username', sa.String(length=80), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.Enum('admin', 'operator', 'viewer', name='user_role'), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('display_name', sa.String(length=120), nullable=True),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_role'), ['role'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_username'), ['username'], unique=True)


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_username'))
        batch_op.drop_index(batch_op.f('ix_user_role'))

    op.drop_table('user')
