"""index what the document lists search and the To do holds read.

Revision ID: doc_list_reads01
Revises: doc_home_shelf01
Create Date: 2026-10-25

A search of the documents list matches a document's number, reference,
notes and partner, and the product names and brands on its lines; To do
asks which completed receipts still hold goods back. Neither had an index
to answer it: at a hundred thousand products every search read 64 000
documents and 950 000 lines, and every To do the lines again. The trigram
indexes serve the search's ``ILIKE`` and regular expression; the partial
index holds only the few lines that hold something back.

Downgrade drops the indexes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'doc_list_reads01'
down_revision: str | None = 'doc_home_shelf01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: (index name, table, indexed expression) of the trigram indexes.
TRIGRAM_INDEXES = (
    ('ix_document_lines_name_trgm', 'document_lines', 'name'),
    ('ix_document_lines_brand_trgm', 'document_lines', 'brand'),
    ('ix_documents_number_trgm', 'documents', 'number'),
    ('ix_documents_external_reference_trgm', 'documents', 'external_reference'),
    ('ix_documents_notes_trgm', 'documents', 'notes'),
    ('ix_documents_partner_name_trgm', 'documents', "(partner_snapshot ->> 'name')"),
)


def upgrade() -> None:
    # The core baseline creates the extension; a module chain run on its own
    # (a fresh database, a test of the chain) must not depend on that.
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    for name, table, expression in TRIGRAM_INDEXES:
        op.execute(
            f'CREATE INDEX IF NOT EXISTS {name} '
            f'ON {table} USING gin ({expression} gin_trgm_ops)'
        )
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_document_lines_held '
        'ON document_lines (document_id) WHERE held_quantity > 0'
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS ix_document_lines_held')
    for name, _table, _expression in TRIGRAM_INDEXES:
        op.execute(f'DROP INDEX IF EXISTS {name}')
