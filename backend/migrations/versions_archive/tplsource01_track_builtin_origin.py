"""track which built-in a copied template came from

Revision ID: tplsource01
Revises: orgissuer01
Create Date: 2026-08-25

An organization that copied a built-in layout prints from its own
copy for good — the copy is theirs and nothing may overwrite it. What was
missing was any way to notice that the built-in it came from has since
changed, so a copy made in 2026 kept printing a barcode geometry that the
measurement had already rejected, with nothing on the screen to say so.

These two columns record the provenance. They are informational: the drift
they make visible is answered by creating a new copy alongside, never by
rewriting the one an organization has been editing.
"""

import sqlalchemy as sa
from alembic import op

revision = 'tplsource01'
down_revision = 'orgissuer01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'document_templates',
        sa.Column('source_builtin', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'document_templates',
        sa.Column('source_checksum', sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('document_templates', 'source_checksum')
    op.drop_column('document_templates', 'source_builtin')
