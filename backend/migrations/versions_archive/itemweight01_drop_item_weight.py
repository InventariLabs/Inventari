"""Drop items.weight — the unit weight belongs to the product template.

Revision ID: itemweight01
Revises: storagecode01
Create Date: 2026-08-15

``items.weight`` had no agreed meaning: the write path treated it as the
weight of the whole line, the read path as the weight of one piece, and the
column carried no unit at all. The form multiplied the value by the quantity
on every save because of it.

The better model already existed and was in use: ``product_templates``
carries ``weight_value`` together with ``weight_uom_id``, i.e. a value with
its unit, meaning the weight of a single unit. The weight of a line is
``quantity × weight_value`` and is computed on read
(``Item.total_weight``) — see ADR-015.

No backfill: the column was empty in every environment checked before this
migration was written. If some other environment has values, capture them
before upgrading — the downgrade restores the column, not its contents.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'itemweight01'
down_revision: str | None = 'storagecode01'
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = 'items'
_COLUMN = 'weight'


def upgrade() -> None:
    op.drop_column(_TABLE, _COLUMN)


def downgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.Numeric(10, 2), nullable=True),
    )
