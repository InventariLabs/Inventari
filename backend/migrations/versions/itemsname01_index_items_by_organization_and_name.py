"""index records and products by organization and name

The smart alerts and the purchase patterns look records up by a list of
names. Nothing but the trigram index on ``items.name`` could answer that,
and the planner used it: a bitmap scan of 3.3 to 6.8 seconds for about two
thousand rows at 100 000 products. A b-tree on
``(organization_id, is_deleted, name)`` answers the same lookup in
milliseconds.

The import finds the card each row joins by name, and meets the same trigram
index on ``product_templates.name``; it gets a b-tree of its own.

Revision ID: itemsname01
Revises: itemtypes01
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'itemsname01'
down_revision: str | None = 'itemtypes01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: Hand-built, and owned by this migration in
#: ``autogenerate_scope.MIGRATION_OWNED_INDEXES``: a database stamped from the
#: previous chain gets them from this revision, after the stamp has compared
#: its schema with the models. ``is_deleted`` sits in the items key because
#: every lookup by name asks for live records only.
INDEXES = (
    ('ix_items_org_name', 'items', 'organization_id, is_deleted, name'),
    ('ix_product_templates_org_name', 'product_templates', 'organization_id, name'),
)


def upgrade() -> None:
    for name, table, columns in INDEXES:
        op.execute(f'CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})')


def downgrade() -> None:
    for name, _table, _columns in INDEXES:
        op.execute(f'DROP INDEX IF EXISTS {name}')
