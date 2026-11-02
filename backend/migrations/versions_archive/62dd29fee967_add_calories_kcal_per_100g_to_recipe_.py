"""add_calories_kcal_per_100g_to_recipe_ingredients

Revision ID: 62dd29fee967
Revises: 9b62c30a2fbd
Create Date: 2026-03-19 21:18:34.072598

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '62dd29fee967'
down_revision: Union[str, None] = '9b62c30a2fbd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col"
        ),
        {"table": table_name, "col": column_name},
    )
    return result.fetchone() is not None


def _safe_alter(table_name, column_name, **kwargs):
    if _col_exists(table_name, column_name):
        op.alter_column(table_name, column_name, **kwargs)


def upgrade() -> None:
    _safe_alter('ai_usage_logs', 'prompt_tokens',
               existing_type=sa.INTEGER(),
               nullable=False)
    _safe_alter('ai_usage_logs', 'completion_tokens',
               existing_type=sa.INTEGER(),
               nullable=False)
    _safe_alter('ai_usage_logs', 'total_tokens',
               existing_type=sa.INTEGER(),
               nullable=False)
    _safe_alter('ai_usage_logs', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('announcements', 'type',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
    _safe_alter('announcements', 'active_from',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('announcements', 'is_active',
               existing_type=sa.BOOLEAN(),
               nullable=False)
    _safe_alter('announcements', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('categories', 'sort_order',
               existing_type=sa.INTEGER(),
               nullable=False)
    _safe_alter('item_attachments', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('item_history', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('item_type_definitions', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('item_type_definitions', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('items', 'quantity',
               existing_type=sa.NUMERIC(precision=10, scale=3),
               nullable=False)
    _safe_alter('items', 'added_date',
               existing_type=sa.DATE(),
               nullable=False)
    _safe_alter('items', 'is_deleted',
               existing_type=sa.BOOLEAN(),
               nullable=False)
    _safe_alter('items', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('items', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    try:
        op.drop_index('idx_item_active_expiry', table_name='items')
    except Exception:
        pass
    _safe_alter('label_pool', 'is_assigned',
               existing_type=sa.BOOLEAN(),
               nullable=False)
    _safe_alter('label_pool', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('label_pool', 'scan_count',
               existing_type=sa.INTEGER(),
               nullable=False)
    _safe_alter('notifications', 'type',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
    _safe_alter('notifications', 'is_read',
               existing_type=sa.BOOLEAN(),
               nullable=False)
    _safe_alter('notifications', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('organization_invitations', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('organization_invitations', 'is_used',
               existing_type=sa.BOOLEAN(),
               nullable=False)
    _safe_alter('organizations', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('organizations', 'enabled_modules',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               nullable=False)
    _safe_alter('organizations', 'settings',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               nullable=False)
    _safe_alter('picking_session_items', 'status',
               existing_type=sa.VARCHAR(length=20),
               nullable=False,
               existing_server_default=sa.text("'pending'::character varying"))
    _safe_alter('picking_sessions', 'servings',
               existing_type=sa.INTEGER(),
               nullable=False,
               existing_server_default=sa.text('1'))
    _safe_alter('picking_sessions', 'status',
               existing_type=sa.VARCHAR(length=20),
               nullable=False,
               existing_server_default=sa.text("'active'::character varying"))
    _safe_alter('picking_sessions', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False,
               existing_server_default=sa.text('now()'))
    _safe_alter('product_templates', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('product_templates', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    if _col_exists('recipe_ingredients', 'calories_kcal_per_100g'):
        pass
    else:
        try:
            op.add_column('recipe_ingredients', sa.Column('calories_kcal_per_100g', sa.Numeric(precision=8, scale=2), nullable=True))
        except Exception:
            pass
    _safe_alter('recipe_ingredients', 'is_optional',
               existing_type=sa.BOOLEAN(),
               nullable=False,
               existing_server_default=sa.text('false'))
    _safe_alter('recipe_ingredients', 'sort_order',
               existing_type=sa.INTEGER(),
               nullable=False,
               existing_server_default=sa.text('0'))
    _safe_alter('recipes', 'servings',
               existing_type=sa.INTEGER(),
               nullable=False,
               existing_server_default=sa.text('1'))
    _safe_alter('recipes', 'is_favorite',
               existing_type=sa.BOOLEAN(),
               nullable=False,
               existing_server_default=sa.text('false'))
    _safe_alter('recipes', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False,
               existing_server_default=sa.text('now()'))
    _safe_alter('recipes', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False,
               existing_server_default=sa.text('now()'))
    _safe_alter('registration_requests', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('registration_requests', 'is_rejected',
               existing_type=sa.BOOLEAN(),
               nullable=False,
               existing_server_default=sa.text('false'))
    _safe_alter('roles', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('shopping_list_items', 'quantity',
               existing_type=sa.INTEGER(),
               nullable=False)
    _safe_alter('shopping_list_items', 'is_purchased',
               existing_type=sa.BOOLEAN(),
               nullable=False)
    _safe_alter('shopping_list_items', 'source',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
    _safe_alter('shopping_list_items', 'priority',
               existing_type=sa.INTEGER(),
               nullable=False)
    _safe_alter('shopping_list_items', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('shopping_list_items', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('shopping_lists', 'name',
               existing_type=sa.VARCHAR(length=255),
               nullable=False)
    _safe_alter('shopping_lists', 'is_active',
               existing_type=sa.BOOLEAN(),
               nullable=False)
    _safe_alter('shopping_lists', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('shopping_lists', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('stock_take_items', 'is_discrepancy',
               existing_type=sa.INTEGER(),
               nullable=False)
    _safe_alter('stock_take_items', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('stock_take_items', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('stock_takes', 'started_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('stock_takes', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('stock_takes', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('storage_locations', 'short_code',
               existing_type=sa.VARCHAR(length=20),
               type_=sa.String(length=100),
               existing_nullable=True)
    _safe_alter('storage_locations', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('storage_types', 'is_system',
               existing_type=sa.BOOLEAN(),
               nullable=False)
    _safe_alter('system_settings', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('uoms', 'is_reference',
               existing_type=sa.BOOLEAN(),
               nullable=False)
    _safe_alter('uoms', 'rounding',
               existing_type=sa.DOUBLE_PRECISION(precision=53),
               nullable=False)
    _safe_alter('users', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('users', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=False)
    _safe_alter('users', 'role',
               existing_type=sa.VARCHAR(length=50),
               nullable=False)
    _safe_alter('users', 'is_active',
               existing_type=sa.BOOLEAN(),
               nullable=False,
               existing_server_default=sa.text('false'))
    _safe_alter('users', 'is_superuser',
               existing_type=sa.BOOLEAN(),
               nullable=False,
               existing_server_default=sa.text('false'))
    _safe_alter('users', 'is_blocked',
               existing_type=sa.BOOLEAN(),
               nullable=False,
               existing_server_default=sa.text('false'))
    _safe_alter('webhook_delivery_logs', 'next_retry_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               type_=sa.DateTime(),
               existing_nullable=True)
    _safe_alter('webhook_delivery_logs', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               type_=sa.DateTime(),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    _safe_alter('webhook_endpoints', 'last_triggered_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               type_=sa.DateTime(),
               existing_nullable=True)
    _safe_alter('webhook_endpoints', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               type_=sa.DateTime(),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    _safe_alter('webhook_endpoints', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               type_=sa.DateTime(),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('webhook_endpoints', 'updated_at',
               existing_type=sa.DateTime(),
               type_=postgresql.TIMESTAMP(timezone=True),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('webhook_endpoints', 'created_at',
               existing_type=sa.DateTime(),
               type_=postgresql.TIMESTAMP(timezone=True),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('webhook_endpoints', 'last_triggered_at',
               existing_type=sa.DateTime(),
               type_=postgresql.TIMESTAMP(timezone=True),
               existing_nullable=True)
    op.alter_column('webhook_delivery_logs', 'created_at',
               existing_type=sa.DateTime(),
               type_=postgresql.TIMESTAMP(timezone=True),
               existing_nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('webhook_delivery_logs', 'next_retry_at',
               existing_type=sa.DateTime(),
               type_=postgresql.TIMESTAMP(timezone=True),
               existing_nullable=True)
    op.alter_column('users', 'is_blocked',
               existing_type=sa.BOOLEAN(),
               nullable=True,
               existing_server_default=sa.text('false'))
    op.alter_column('users', 'is_superuser',
               existing_type=sa.BOOLEAN(),
               nullable=True,
               existing_server_default=sa.text('false'))
    op.alter_column('users', 'is_active',
               existing_type=sa.BOOLEAN(),
               nullable=True,
               existing_server_default=sa.text('false'))
    op.alter_column('users', 'role',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)
    op.alter_column('users', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('users', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('uoms', 'rounding',
               existing_type=sa.DOUBLE_PRECISION(precision=53),
               nullable=True)
    op.alter_column('uoms', 'is_reference',
               existing_type=sa.BOOLEAN(),
               nullable=True)
    op.alter_column('system_settings', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('storage_types', 'is_system',
               existing_type=sa.BOOLEAN(),
               nullable=True)
    op.alter_column('storage_locations', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('storage_locations', 'short_code',
               existing_type=sa.String(length=100),
               type_=sa.VARCHAR(length=20),
               existing_nullable=True)
    op.alter_column('stock_takes', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('stock_takes', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('stock_takes', 'started_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('stock_take_items', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('stock_take_items', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('stock_take_items', 'is_discrepancy',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('shopping_lists', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('shopping_lists', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('shopping_lists', 'is_active',
               existing_type=sa.BOOLEAN(),
               nullable=True)
    op.alter_column('shopping_lists', 'name',
               existing_type=sa.VARCHAR(length=255),
               nullable=True)
    op.alter_column('shopping_list_items', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('shopping_list_items', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('shopping_list_items', 'priority',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('shopping_list_items', 'source',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)
    op.alter_column('shopping_list_items', 'is_purchased',
               existing_type=sa.BOOLEAN(),
               nullable=True)
    op.alter_column('shopping_list_items', 'quantity',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('roles', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('registration_requests', 'is_rejected',
               existing_type=sa.BOOLEAN(),
               nullable=True,
               existing_server_default=sa.text('false'))
    op.alter_column('registration_requests', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('recipes', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.alter_column('recipes', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.alter_column('recipes', 'is_favorite',
               existing_type=sa.BOOLEAN(),
               nullable=True,
               existing_server_default=sa.text('false'))
    op.alter_column('recipes', 'servings',
               existing_type=sa.INTEGER(),
               nullable=True,
               existing_server_default=sa.text('1'))
    op.alter_column('recipe_ingredients', 'sort_order',
               existing_type=sa.INTEGER(),
               nullable=True,
               existing_server_default=sa.text('0'))
    op.alter_column('recipe_ingredients', 'is_optional',
               existing_type=sa.BOOLEAN(),
               nullable=True,
               existing_server_default=sa.text('false'))
    op.drop_column('recipe_ingredients', 'calories_kcal_per_100g')
    op.alter_column('product_templates', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('product_templates', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('picking_sessions', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.alter_column('picking_sessions', 'status',
               existing_type=sa.VARCHAR(length=20),
               nullable=True,
               existing_server_default=sa.text("'active'::character varying"))
    op.alter_column('picking_sessions', 'servings',
               existing_type=sa.INTEGER(),
               nullable=True,
               existing_server_default=sa.text('1'))
    op.alter_column('picking_session_items', 'status',
               existing_type=sa.VARCHAR(length=20),
               nullable=True,
               existing_server_default=sa.text("'pending'::character varying"))
    op.alter_column('organizations', 'settings',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               nullable=True)
    op.alter_column('organizations', 'enabled_modules',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               nullable=True)
    op.alter_column('organizations', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('organization_invitations', 'is_used',
               existing_type=sa.BOOLEAN(),
               nullable=True)
    op.alter_column('organization_invitations', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('notifications', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('notifications', 'is_read',
               existing_type=sa.BOOLEAN(),
               nullable=True)
    op.alter_column('notifications', 'type',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)
    op.alter_column('label_pool', 'scan_count',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('label_pool', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('label_pool', 'is_assigned',
               existing_type=sa.BOOLEAN(),
               nullable=True)
    op.create_index('idx_item_active_expiry', 'items', ['is_deleted', 'expiry_date'], unique=False)
    op.alter_column('items', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('items', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('items', 'is_deleted',
               existing_type=sa.BOOLEAN(),
               nullable=True)
    op.alter_column('items', 'added_date',
               existing_type=sa.DATE(),
               nullable=True)
    op.alter_column('items', 'quantity',
               existing_type=sa.NUMERIC(precision=10, scale=3),
               nullable=True)
    op.alter_column('item_type_definitions', 'updated_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('item_type_definitions', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('item_history', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('item_attachments', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('categories', 'sort_order',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('announcements', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('announcements', 'is_active',
               existing_type=sa.BOOLEAN(),
               nullable=True)
    op.alter_column('announcements', 'active_from',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('announcements', 'type',
               existing_type=sa.VARCHAR(length=50),
               nullable=True)
    op.alter_column('ai_usage_logs', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               nullable=True)
    op.alter_column('ai_usage_logs', 'total_tokens',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('ai_usage_logs', 'completion_tokens',
               existing_type=sa.INTEGER(),
               nullable=True)
    op.alter_column('ai_usage_logs', 'prompt_tokens',
               existing_type=sa.INTEGER(),
               nullable=True)
    # ### end Alembic commands ###
