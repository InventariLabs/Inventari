"""Add stock_takes.adjustment_document_id: the document a count posted.

Revision ID: 013_a_count_names_its_adjustment
Revises: 012_a_count_names_its_schedule
Create Date: 2026-10-20

Closing a count with differences now leaves one stock adjustment in the
documents register, and the count keeps which one, so its report can open it.
The document belongs to another module, so the column is a plain id with no
foreign key: the documents module may be switched off, and a count must not
depend on it. Counts closed before this column stay unlinked.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '013_a_count_names_its_adjustment'
down_revision: str | None = '012_a_count_names_its_schedule'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'stock_takes',
        sa.Column(
            'adjustment_document_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('stock_takes', 'adjustment_document_id')
