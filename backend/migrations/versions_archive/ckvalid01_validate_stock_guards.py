"""validate the stock CHECK constraints that were added NOT VALID.

Revision ID: ckvalid01
Revises: svlneg01
Create Date: 2026-09-01

The four guards on `stock_quants` and `items` were added `NOT VALID`, which
skips the table scan and the lock that comes with it — the right call on a
live table — with a note in that migration to validate them separately.
Nobody did.

An unvalidated constraint checks new writes and says nothing about the rows
already there, so the guarantee the earlier migration was written for was
never actually obtained: a database that had a negative quantity in it
before then still has it, and nothing in the schema disagrees. The planner
ignores such a constraint too.

The scan is the point, so it happens here. On a table with a violating row
this migration fails, loudly, naming the constraint — which is the correct
outcome: the data is wrong and clamping it silently would hide by how much.
Clean the row, then run it again.

Downgrade cannot un-validate a constraint in Postgres and there is nothing to
undo — the constraints themselves belong to the migration that added them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'ckvalid01'
down_revision: str | None = 'svlneg01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GUARDS = (
    ('stock_quants', 'ck_stock_quants_quantity_nonneg'),
    ('stock_quants', 'ck_stock_quants_reserved_nonneg'),
    ('stock_quants', 'ck_stock_quants_reserved_le_quantity'),
    ('items', 'ck_items_quantity_nonneg'),
)


def upgrade() -> None:
    for table, name in _GUARDS:
        # A no-op where the constraint is already valid, which is the case on
        # a database created from the models rather than from this chain.
        op.execute(sa.text(f'ALTER TABLE {table} VALIDATE CONSTRAINT {name}'))


def downgrade() -> None:
    pass
