"""the pick line drops the quant it no longer has: wms_pick_lines.quant_id goes

Revision ID: doc_pick_quant_gone01
Revises: doc_pick_group01
Create Date: 2026-09-29

The quant table is gone (core ``quantdrop01``, the one-number stock model
in ADR-022). A picking line has named its group and its batch since
``doc_pick_group01`` — ``anchor_id`` and ``lot_id`` — and the scan matches on
those or on a barcode; the quant row ``quant_id`` pointed at no longer
exists, and the core migration's ``DROP TABLE ... CASCADE`` has already taken
the foreign key off the column. What is left is a column nothing writes or
reads, and it goes.

Downgrade puts the column back, empty and without its foreign key: there is
no quant row for it to name, and a downgrade of the core migration rebuilds
the table from the records rather than restoring the rows the lines named.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_pick_quant_gone01'
down_revision: str | Sequence[str] | None = 'doc_pick_group01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('ALTER TABLE wms_pick_lines DROP COLUMN IF EXISTS quant_id')


def downgrade() -> None:
    op.add_column('wms_pick_lines', sa.Column('quant_id', sa.Uuid(), nullable=True))
