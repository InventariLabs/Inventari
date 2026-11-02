"""add cancelled_by and cancelled_at to approval_requests

Revision ID: c0a1b2c3d4e5
Revises: b0b06a800abb
Create Date: 2026-06-20 10:20:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c0a1b2c3d4e5'
down_revision: Union[str, None] = 'b0b06a800abb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    table_exists = bind.execute(
        sa.text("SELECT to_regclass('public.approval_requests')")
    ).scalar()
    if not table_exists:
        return

    op.add_column(
        'approval_requests', sa.Column('cancelled_by', sa.UUID(), nullable=True)
    )
    op.add_column(
        'approval_requests',
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        'approval_requests_cancelled_by_fkey',
        'approval_requests',
        'users',
        ['cancelled_by'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    bind = op.get_bind()
    table_exists = bind.execute(
        sa.text("SELECT to_regclass('public.approval_requests')")
    ).scalar()
    if not table_exists:
        return

    op.drop_constraint(
        'approval_requests_cancelled_by_fkey', 'approval_requests', type_='foreignkey'
    )
    op.drop_column('approval_requests', 'cancelled_at')
    op.drop_column('approval_requests', 'cancelled_by')
