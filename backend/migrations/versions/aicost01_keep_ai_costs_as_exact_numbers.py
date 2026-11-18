"""keep AI costs as exact numbers

The cost of an AI call was a float, so the totals an administrator reads were
sums of binary approximations: ten calls at ten cents came to
0.9999999999999999. Ten decimal places hold the price of a single token of the
cheapest models, which six would round to nothing.

A value no cost can be (not a number, infinite, or a million dollars and more
for one call) becomes NULL, the column's "cost unknown", which the totals skip.
Refusing it would stop the upgrade, and the backend starts only after that.

Changing the type rewrites the table and blocks it for as long as that takes.
There is one small row per AI call and the backend is waiting for the migration
anyway, which is why this is not the add-a-column, backfill-in-batches, swap
sequence a table the size of ``stock_moves`` would need.

Revision ID: aicost01
Revises: notifinbox01
Create Date: 2026-11-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = 'aicost01'
down_revision: str | None = 'notifinbox01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NaN compares above every number in PostgreSQL, so it fails this test too.
    op.execute(
        'ALTER TABLE ai_usage_logs ALTER COLUMN estimated_cost_usd '
        'TYPE numeric(16, 10) USING CASE '
        'WHEN abs(estimated_cost_usd) < 999999 '
        'THEN round(estimated_cost_usd::numeric, 10) END'
    )


def downgrade() -> None:
    op.execute(
        'ALTER TABLE ai_usage_logs ALTER COLUMN estimated_cost_usd '
        'TYPE double precision USING estimated_cost_usd::double precision'
    )
