"""index the list searches - what the product list reads

At a hundred thousand products the product list read every record of the
organization for a search and for the order by name. A search asks each
field it matches through that field's trigram index; two of those fields had
none (a record's serial number and the product code on its template), so
every search fell back to reading everything. The order by name walks
``ix_items_org_name``, which ``itemsname01`` builds.

Revision ID: listreads01
Revises: itemimportjob01
Create Date: 2026-10-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'listreads01'
down_revision: str | None = 'itemimportjob01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Hand-built like the baseline's trigram indexes, and owned by this
#: migration in ``autogenerate_scope.MIGRATION_OWNED_INDEXES``: a database
#: stamped from the previous chain gets them from this revision, after the
#: stamp has compared its schema with the models.
TRIGRAM_INDEXES = (
    ('ix_items_serial_number_trgm', 'items', 'serial_number'),
    ('ix_product_templates_barcode_trgm', 'product_templates', 'barcode'),
)


def upgrade() -> None:
    for name, table, column in TRIGRAM_INDEXES:
        op.execute(
            f'CREATE INDEX IF NOT EXISTS {name} ON {table} '
            f'USING gin ({column} gin_trgm_ops)'
        )


def downgrade() -> None:
    for name, _table, _column in TRIGRAM_INDEXES:
        op.execute(f'DROP INDEX IF EXISTS {name}')
