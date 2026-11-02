"""rename household domain to organization

Revision ID: 70cc64de9ba4
Revises: 06bdf1d3ad08
Create Date: 2026-02-19 22:12:03.700843

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '70cc64de9ba4'
down_revision: Union[str, None] = '06bdf1d3ad08'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if 'households' in inspector.get_table_names():
        op.rename_table('households', 'organizations')

    inspector = inspect(bind)
    if 'household_invitations' in inspector.get_table_names():
        op.rename_table('household_invitations', 'organization_invitations')

    tables_with_fk = [
        'users',
        'storage_locations',
        'storage_types',
        'categories',
        'items',
        'item_history',
        'label_pool',
        'item_type_definitions',
        'ai_usage_logs',
        'product_templates',
        'shopping_lists',
        'stock_takes',
        'organization_invitations',
    ]

    inspector = inspect(bind)
    for table in tables_with_fk:
        if table not in inspector.get_table_names():
            continue
        columns = {c['name'] for c in inspector.get_columns(table)}
        if 'household_id' in columns and 'organization_id' not in columns:
            op.alter_column(table, 'household_id', new_column_name='organization_id')

    # Rename commonly used indexes if they exist.
    op.execute('ALTER INDEX IF EXISTS ix_households_short_id RENAME TO ix_organizations_short_id')
    op.execute('ALTER INDEX IF EXISTS ix_household_invitations_code RENAME TO ix_organization_invitations_code')
    op.execute('ALTER INDEX IF EXISTS ix_ai_usage_logs_household_id RENAME TO ix_ai_usage_logs_organization_id')
    op.execute('ALTER INDEX IF EXISTS ix_categories_household_id RENAME TO ix_categories_organization_id')
    op.execute('ALTER INDEX IF EXISTS ix_item_history_household_id RENAME TO ix_item_history_organization_id')
    op.execute('ALTER INDEX IF EXISTS ix_item_type_definitions_household_id RENAME TO ix_item_type_definitions_organization_id')
    op.execute('ALTER INDEX IF EXISTS ix_label_pool_household_id RENAME TO ix_label_pool_organization_id')
    op.execute('ALTER INDEX IF EXISTS ix_product_templates_household_id RENAME TO ix_product_templates_organization_id')
    op.execute('ALTER INDEX IF EXISTS ix_storage_locations_household_id RENAME TO ix_storage_locations_organization_id')


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    tables_with_fk = [
        'users',
        'storage_locations',
        'storage_types',
        'categories',
        'items',
        'item_history',
        'label_pool',
        'item_type_definitions',
        'ai_usage_logs',
        'product_templates',
        'shopping_lists',
        'stock_takes',
        'organization_invitations',
    ]

    for table in tables_with_fk:
        if table not in inspector.get_table_names():
            continue
        columns = {c['name'] for c in inspector.get_columns(table)}
        if 'organization_id' in columns and 'household_id' not in columns:
            op.alter_column(table, 'organization_id', new_column_name='household_id')

    if 'organization_invitations' in inspector.get_table_names():
        op.rename_table('organization_invitations', 'household_invitations')

    inspector = inspect(bind)
    if 'organizations' in inspector.get_table_names():
        op.rename_table('organizations', 'households')

    op.execute('ALTER INDEX IF EXISTS ix_organizations_short_id RENAME TO ix_households_short_id')
    op.execute('ALTER INDEX IF EXISTS ix_organization_invitations_code RENAME TO ix_household_invitations_code')
    op.execute('ALTER INDEX IF EXISTS ix_ai_usage_logs_organization_id RENAME TO ix_ai_usage_logs_household_id')
    op.execute('ALTER INDEX IF EXISTS ix_categories_organization_id RENAME TO ix_categories_household_id')
    op.execute('ALTER INDEX IF EXISTS ix_item_history_organization_id RENAME TO ix_item_history_household_id')
    op.execute('ALTER INDEX IF EXISTS ix_item_type_definitions_organization_id RENAME TO ix_item_type_definitions_household_id')
    op.execute('ALTER INDEX IF EXISTS ix_label_pool_organization_id RENAME TO ix_label_pool_household_id')
    op.execute('ALTER INDEX IF EXISTS ix_product_templates_organization_id RENAME TO ix_product_templates_household_id')
    op.execute('ALTER INDEX IF EXISTS ix_storage_locations_organization_id RENAME TO ix_storage_locations_household_id')
