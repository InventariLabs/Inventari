"""fill in the unit on document lines that name a product carrying one.

Revision ID: doc_line_unit_backfill01
Revises: doc_neutral_type_codes01
Create Date: 2026-09-09

A line naming a record on a shelf used to keep the record's name and lose
its unit: only a catalogue entry passed one on. Every reader downstream then
printed a bare quantity — the picker's row, the execution sheet, the PDF —
and "3" tells a warehouseman nothing, since three pieces, three packs and
three kilograms are three different picks.

The write path now takes the unit off the record the line names. This fills
in the lines written before it did, from the same two sources and in the
same order: the record first, the catalogue entry second. Lines whose
product never had a unit stay empty, which is the honest answer.

Both source tables belong to the core, so each statement is guarded — a
module migration runs on installs where they may be absent.

Downgrade does nothing on purpose: which rows were empty before is not
recorded anywhere, and blanking every unit would lose the ones the write
path put there legitimately.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_line_unit_backfill01'
down_revision: str | None = 'doc_neutral_type_codes01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text('SELECT to_regclass(:name)'), {'name': f'public.{name}'}
        ).scalar()
    )


def upgrade() -> None:
    if not _table_exists('document_lines'):
        return
    if _table_exists('items'):
        op.execute(
            sa.text(
                """
                UPDATE document_lines dl
                SET uom_id = i.uom_id
                FROM items i
                WHERE dl.item_id = i.id
                  AND dl.uom_id IS NULL
                  AND i.uom_id IS NOT NULL
                """
            )
        )
    if _table_exists('product_templates'):
        op.execute(
            sa.text(
                """
                UPDATE document_lines dl
                SET uom_id = pt.uom_id
                FROM product_templates pt
                WHERE dl.product_template_id = pt.id
                  AND dl.uom_id IS NULL
                  AND pt.uom_id IS NOT NULL
                """
            )
        )


def downgrade() -> None:
    """Nothing to undo — see the module docstring."""
