"""add the pick-order strategy to the document profile.

Revision ID: doc_pick_order_strategy01
Revises: doc_meta_data01
Create Date: 2026-10-23

``document_profiles.pick_order_strategy`` names the strategy the warehouse
is walked by while picking — one of the registered pick orders
(``pick_order_strategies``). ``NULL`` is "nothing chosen", which walks the
default: the order the locations are numbered.

``doc_meta_data01`` branched from ``doc_held_by02`` in parallel and landed
first; this revision is rebased onto it so ``alembic upgrade head`` keeps a
single head.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_pick_order_strategy01'
down_revision: str | None = 'doc_meta_data01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'document_profiles',
        sa.Column('pick_order_strategy', sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('document_profiles', 'pick_order_strategy')
