"""Fix uq_items_org_serial drift and add missing hot-path indexes.

Revision ID: coreaudit01
Revises: orglabel01
Create Date: 2026-07-28

Two fixes found in a review of the core:

1. Schema drift: the Item model declares a PARTIAL unique index
``uq_items_org_serial`` (WHERE serial_number IS NOT NULL AND is_deleted =
false), but baseline_001_full_schema created a FULL unique index on
(organization_id, serial_number). The full variant incorrectly blocks
serial-number reuse after soft delete. This migration replaces the full
index with the partial one. Data valid under the full index is always
valid under the partial index, so the swap cannot fail on existing data.

2. Missing indexes used by hot queries:
  - item_history (item_id, created_at)          — per-item history views
  - audit_log (target_type, target_id)          — per-target audit lookups
  - audit_log (created_at)                      — time-range scans
  - items (organization_id, is_deleted, created_at DESC) — default list
  - users (organization_id)                     — org membership lookups
  - stock_packages (parent_id)                  — package nesting tree
  - stock_moves (created_at)                    — move journal ordering
  - items meta_data GIN                         — namespaced meta lookups
And drop ix_items_quantity: equality/range filters on quantity are not a
query pattern used anywhere, and the column changes on every stock
mutation, so the index is pure write amplification.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'coreaudit01'
down_revision: str | None = 'orglabel01'
branch_labels: str | None = None
depends_on: str | None = None


def _index_exists(index_name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text('SELECT to_regclass(:t)'),
            {'t': f'public.{index_name}'},
        ).scalar()
    )


def upgrade() -> None:
    # #4 — replace the full unique index with the partial one from the model.
    if _index_exists('uq_items_org_serial'):
        op.drop_index('uq_items_org_serial', table_name='items')
    op.execute(
        """
        CREATE UNIQUE INDEX uq_items_org_serial
        ON items (organization_id, serial_number)
        WHERE serial_number IS NOT NULL AND is_deleted = false
        """
    )

    # #5 — add the missing indexes.
    if not _index_exists('ix_item_history_item_created'):
        op.create_index(
            'ix_item_history_item_created',
            'item_history',
            ['item_id', 'created_at'],
        )
    if not _index_exists('ix_audit_log_target'):
        op.create_index(
            'ix_audit_log_target',
            'audit_log',
            ['target_type', 'target_id'],
        )
    if not _index_exists('ix_audit_log_created_at'):
        op.create_index('ix_audit_log_created_at', 'audit_log', ['created_at'])
    if not _index_exists('ix_items_org_created'):
        op.create_index(
            'ix_items_org_created',
            'items',
            ['organization_id', 'is_deleted', sa.text('created_at DESC')],
        )
    if not _index_exists('ix_users_organization_id'):
        op.create_index('ix_users_organization_id', 'users', ['organization_id'])
    if not _index_exists('ix_stock_packages_parent_id'):
        op.create_index(
            'ix_stock_packages_parent_id', 'stock_packages', ['parent_id']
        )
    if not _index_exists('ix_stock_moves_created_at'):
        op.create_index('ix_stock_moves_created_at', 'stock_moves', ['created_at'])
    if not _index_exists('ix_items_meta_data_gin'):
        op.create_index(
            'ix_items_meta_data_gin',
            'items',
            ['meta_data'],
            postgresql_using='gin',
        )

    # #5 — drop the unused quantity index (write amplification).
    if _index_exists('ix_items_quantity'):
        op.drop_index('ix_items_quantity', table_name='items')


def downgrade() -> None:
    if not _index_exists('ix_items_quantity'):
        op.create_index('ix_items_quantity', 'items', ['quantity'])

    if _index_exists('ix_items_meta_data_gin'):
        op.drop_index('ix_items_meta_data_gin', table_name='items')
    if _index_exists('ix_stock_moves_created_at'):
        op.drop_index('ix_stock_moves_created_at', table_name='stock_moves')
    if _index_exists('ix_stock_packages_parent_id'):
        op.drop_index('ix_stock_packages_parent_id', table_name='stock_packages')
    if _index_exists('ix_users_organization_id'):
        op.drop_index('ix_users_organization_id', table_name='users')
    if _index_exists('ix_items_org_created'):
        op.drop_index('ix_items_org_created', table_name='items')
    if _index_exists('ix_audit_log_created_at'):
        op.drop_index('ix_audit_log_created_at', table_name='audit_log')
    if _index_exists('ix_audit_log_target'):
        op.drop_index('ix_audit_log_target', table_name='audit_log')
    if _index_exists('ix_item_history_item_created'):
        op.drop_index('ix_item_history_item_created', table_name='item_history')

    # Restore the full unique index. Fails only if soft-deleted duplicates
    # were created while the partial index was active — dedupe first.
    if _index_exists('uq_items_org_serial'):
        op.drop_index('uq_items_org_serial', table_name='items')
    op.create_index(
        'uq_items_org_serial',
        'items',
        ['organization_id', 'serial_number'],
        unique=True,
    )
