"""drop cross-module fks documents_purchase_orders recipes_shopping_lists

Revision ID: 30cec1e60faf
Revises: baseline_001
Create Date: 2026-06-10 15:43:51.076941

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '30cec1e60faf'
down_revision: Union[str, None] = 'baseline_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _constraint_exists(table: str, constraint: str) -> bool:
    bind = op.get_bind()
    if not bind.execute(
        sa.text('SELECT to_regclass(:t)'), {'t': f'public.{table}'}
    ).scalar():
        return False
    result = bind.execute(
        sa.text(
            'SELECT 1 FROM pg_constraint '
            'WHERE conrelid = CAST(:table AS regclass) AND conname = :cname'
        ),
        {'table': table, 'cname': constraint},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    if _constraint_exists('document_lines', 'fk_document_lines_source_po_line_id'):
        op.drop_constraint(
            'fk_document_lines_source_po_line_id',
            'document_lines',
            type_='foreignkey',
        )
    if _constraint_exists('meal_plans', 'meal_plans_shopping_list_id_fkey'):
        op.drop_constraint(
            'meal_plans_shopping_list_id_fkey',
            'meal_plans',
            type_='foreignkey',
        )


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text('SELECT to_regclass(:t)'), {'t': f'public.{table_name}'}
        ).scalar()
    )


def downgrade() -> None:
    if _table_exists('meal_plans') and _table_exists('shopping_lists'):
        op.create_foreign_key(
            'meal_plans_shopping_list_id_fkey',
            'meal_plans',
            'shopping_lists',
            ['shopping_list_id'],
            ['id'],
            ondelete='SET NULL',
        )
    if _table_exists('document_lines') and _table_exists('purchase_order_lines'):
        op.create_foreign_key(
            'fk_document_lines_source_po_line_id',
            'document_lines',
            'purchase_order_lines',
            ['source_po_line_id'],
            ['id'],
            ondelete='SET NULL',
        )
