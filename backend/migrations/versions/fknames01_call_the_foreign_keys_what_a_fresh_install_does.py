"""give a database stamped from the previous chain the names a fresh install has

The previous chain named the core foreign keys itself
(``fk_<table>_<column>_<referred table>``); ``baseline_002`` declares most of
them unnamed, so a database built from it carries PostgreSQL's
``<table>_<column>_fkey``. A later revision that drops a foreign key by name
would then work on one of the two and stop the other. The release's
installations and the databases built from the models all have PostgreSQL's
names, so the stamped database is the one that moves.

``uq_partner_org_code`` is the same split: the previous chain kept it a plain
unique index, the baseline and the model make it partial. Uniqueness is the
same, because NULLs never collide, but only one definition should exist.

Only names a database actually carries are touched, so a database that began
on the baseline sees no change. ``downgrade`` is a documented no-op: nothing
afterwards says which of the two kinds of database this was, and renaming back
would split a fresh install from its own models.

Revision ID: fknames01
Revises: ledgertotals02
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'fknames01'
down_revision: str | None = 'ledgertotals02'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The one key the baseline names itself, the way the model does.
_NAMED_BY_THE_BASELINE = {'fk_label_pool_item_id_items': 'fk_label_pool_item_id'}

#: Frozen from a database at the previous chain's last revision. A name absent
#: here is the same on both kinds of database.
_PREVIOUS_CHAIN_NAMES = (
    'fk_ai_usage_logs_organization_id_organizations',
    'fk_ai_usage_logs_user_id_users',
    'fk_audit_log_organization_id_organizations',
    'fk_audit_log_user_id_users',
    'fk_categories_organization_id_organizations',
    'fk_document_templates_created_by_users',
    'fk_document_templates_organization_id_organizations',
    'fk_item_attachments_item_id_items',
    'fk_item_history_item_id_items',
    'fk_item_history_organization_id_organizations',
    'fk_item_history_user_id_users',
    'fk_items_category_id_categories',
    'fk_items_deleted_by_users',
    'fk_items_lot_id',
    'fk_items_organization_id_organizations',
    'fk_items_owner_id',
    'fk_items_partner_id_partners',
    'fk_items_storage_location_id_storage_locations',
    'fk_items_template_id_product_templates',
    'fk_items_uom_id_uoms',
    'fk_label_pool_created_by_users',
    'fk_label_pool_item_id_items',
    'fk_label_pool_organization_id_organizations',
    'fk_label_pool_target_storage_location_id_storage_locations',
    'fk_notifications_user_id_users',
    'fk_organization_invitations_created_by_users',
    'fk_organization_invitations_organization_id_organizations',
    'fk_organization_invitations_role_id',
    'fk_organization_invitations_used_by_user_id_users',
    'fk_partners_created_by_users',
    'fk_partners_organization_id_organizations',
    'fk_product_templates_organization_id_organizations',
    'fk_product_templates_uom_id_uoms',
    'fk_product_templates_volume_uom_id_uoms',
    'fk_product_templates_weight_uom_id_uoms',
    'fk_registration_requests_approved_by_id_users',
    'fk_roles_organization_id_organizations',
    'fk_stock_lots_organization_id_organizations',
    'fk_stock_lots_product_template_id_product_templates',
    'fk_stock_valuation_layers_organization_id_organizations',
    'fk_stock_valuation_layers_product_template_id_product_templates',
    'fk_storage_locations_created_by_users',
    'fk_storage_locations_organization_id_organizations',
    'fk_storage_locations_parent_id_storage_locations',
    'fk_storage_locations_storage_type_id_storage_types',
    'fk_storage_types_created_by_users',
    'fk_storage_types_organization_id_organizations',
    'fk_system_settings_updated_by_users',
    'fk_uom_categories_organization_id_organizations',
    'fk_uoms_category_id_uom_categories',
    'fk_uoms_organization_id_organizations',
    'fk_user_roles_role_id_roles',
    'fk_user_roles_user_id_users',
)


def _rename_foreign_keys(bind: sa.Connection) -> None:
    rows = bind.execute(
        sa.text(
            'SELECT t.relname, c.conname, a.attname '
            'FROM pg_constraint c '
            'JOIN pg_class t ON t.oid = c.conrelid '
            'JOIN pg_namespace n ON n.oid = t.relnamespace '
            'JOIN pg_attribute a '
            '  ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] '
            "WHERE n.nspname = current_schema() AND c.contype = 'f' "
            'AND c.conname = ANY(:names)'
        ),
        {'names': list(_PREVIOUS_CHAIN_NAMES)},
    ).all()
    for table, name, column in rows:
        new_name = _NAMED_BY_THE_BASELINE.get(name, f'{table}_{column}_fkey')
        op.execute(f'ALTER TABLE {table} RENAME CONSTRAINT {name} TO {new_name}')


def _make_the_partner_code_index_partial(bind: sa.Connection) -> None:
    definition = bind.execute(
        sa.text(
            'SELECT indexdef FROM pg_indexes '
            "WHERE schemaname = current_schema() AND indexname = 'uq_partner_org_code'"
        )
    ).scalar()
    if definition is None or ' WHERE ' in definition:
        return
    op.drop_index('uq_partner_org_code', table_name='partners')
    op.create_index(
        'uq_partner_org_code',
        'partners',
        ['organization_id', 'code'],
        unique=True,
        postgresql_where=sa.text('code IS NOT NULL'),
    )


def upgrade() -> None:
    bind = op.get_bind()
    _rename_foreign_keys(bind)
    _make_the_partner_code_index_partial(bind)


def downgrade() -> None:
    # Nothing to undo: see the module docstring.
    pass
