"""add shopping_list_history and example_widgets tables

Revision ID: e4f5a6b7c8d9
Revises: d1e2f3a4b5c6
Create Date: 2026-06-20 11:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text("SELECT to_regclass(:t)"), {'t': f'public.{table_name}'}
        ).scalar()
    )


def upgrade() -> None:
    if not _table_exists('shopping_list_history'):
        # shopping_list_history
        op.create_table(
            'shopping_list_history',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column(
                'organization_id',
                UUID(as_uuid=True),
                sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                nullable=False,
                index=True,
            ),
            sa.Column('original_list_id', UUID(as_uuid=True), nullable=False, index=True),
            sa.Column('original_list_name', sa.String(255), nullable=False),
            sa.Column('item_name', sa.String(255), nullable=False),
            sa.Column('quantity', sa.Numeric(12, 3), nullable=False, server_default='1'),
            sa.Column('estimated_price', sa.Numeric(10, 2), nullable=True),
            sa.Column('purchased_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                'purchased_by',
                UUID(as_uuid=True),
                sa.ForeignKey('users.id'),
                nullable=True,
            ),
            sa.Column(
                'archived_at',
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    if not _table_exists('example_widgets'):
        # example_widgets
        op.create_table(
            'example_widgets',
            sa.Column('id', UUID(as_uuid=True), primary_key=True),
            sa.Column(
                'organization_id',
                UUID(as_uuid=True),
                sa.ForeignKey('organizations.id', ondelete='CASCADE'),
                nullable=False,
                index=True,
            ),
            sa.Column('name', sa.String(100), nullable=False),
            sa.Column('color', sa.String(30), nullable=False, server_default='blue'),
            sa.Column('quantity', sa.Integer(), nullable=False, server_default='0'),
            sa.Column(
                'is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')
            ),
            sa.Column(
                'created_at',
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                'updated_at',
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )


def downgrade() -> None:
    if _table_exists('example_widgets'):
        op.drop_table('example_widgets')
    if _table_exists('shopping_list_history'):
        op.drop_table('shopping_list_history')
