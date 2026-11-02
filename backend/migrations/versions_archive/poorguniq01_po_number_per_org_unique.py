"""PO number unique per organization instead of globally.

Revision ID: poorguniq01
Revises: droplotnum01
Create Date: 2026-06-19

"""

import sqlalchemy as sa
from alembic import op  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = 'poorguniq01'
down_revision: str | None = 'droplotnum01'
branch_labels: str | None = None
depends_on: str | None = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text('SELECT to_regclass(:t)'), {'t': f'public.{table_name}'}
        ).scalar()
    )


def _index_exists(index_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text('SELECT to_regclass(:t)'),
            {'t': f'public.{index_name}'},
        ).scalar()
    )


def _constraint_exists(constraint_name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            'SELECT 1 FROM pg_constraint '
            "WHERE conname = :c AND conrelid = 'public.purchase_orders'::regclass"
        ),
        {'c': constraint_name},
    ).first()
    return row is not None


def _index_is_unique(index_name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text('SELECT indisunique FROM pg_index WHERE indexrelid = :r'),
        {'r': f'public.{index_name}'},
    ).first()
    return bool(row and row[0])


def upgrade() -> None:
    if not _table_exists('purchase_orders'):
        return

    if _index_exists('ix_purchase_orders_number'):
        op.drop_index('ix_purchase_orders_number', table_name='purchase_orders')

    op.create_index(
        'ix_purchase_orders_number',
        'purchase_orders',
        ['number'],
        unique=False,
    )

    if not _constraint_exists('uq_purchase_orders_org_number'):
        op.create_unique_constraint(
            'uq_purchase_orders_org_number',
            'purchase_orders',
            ['organization_id', 'number'],
        )


def downgrade() -> None:
    if not _table_exists('purchase_orders'):
        return

    if _constraint_exists('uq_purchase_orders_org_number'):
        op.drop_constraint(
            'uq_purchase_orders_org_number',
            'purchase_orders',
            type_='unique',
        )

    if _index_exists('ix_purchase_orders_number'):
        op.drop_index('ix_purchase_orders_number', table_name='purchase_orders')

    op.create_index(
        'ix_purchase_orders_number',
        'purchase_orders',
        ['number'],
        unique=True,
    )
