"""add print_snapshot to documents.

Revision ID: doc_print_snapshot01
Revises: doc_tax_assign01
Create Date: 2026-11-03

A confirmed document already keeps its partner as it was. The printout also
states the issuer (the organization's name, tax id and address) and the names
of the places the goods moved between; those were read on every print, so a
reprint after the company moved showed the new address on an old document.
The column keeps them from confirmation on. Existing rows stay empty and
print from live data.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'doc_print_snapshot01'
down_revision: str | None = 'doc_tax_assign01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('print_snapshot', postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('documents', 'print_snapshot')
