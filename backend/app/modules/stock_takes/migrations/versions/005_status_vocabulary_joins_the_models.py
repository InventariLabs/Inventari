"""The status and cycle-count vocabularies join the models'.

A database that ran the pre-squash chain carries three enum types with the
labels the old core migration wrote — the members' *names*, uppercase — while
the models persist the StrEnum *values*, lowercase. A fresh database never sees
the split: the module baseline creates the types itself, with the values. A
database whose module baseline was stamped over the core tables kept the old
labels, and from then on every write died on ``invalid input value for enum``,
which is invisible to a suite that builds its schema from the models.

Renaming the labels in place is safe for the rows: an enum value is a sort
order in the catalogue, not a text in the column, so ``RENAME VALUE`` moves the
label every row already wears. Values the old chain never created are added
afterwards. On a fresh database every step is a no-op.

Revision ID: 005_status_vocabulary
Revises: 004_stock_take_counts
Create Date: 2026-09-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '005_status_vocabulary'
down_revision: str | None = '004_stock_take_counts'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Enum type -> the labels the models persist, in the order the type declares.
_VOCABULARIES: dict[str, tuple[str, ...]] = {
    'stocktakestatus': ('draft', 'in_progress', 'completed', 'cancelled'),
    'cyclecountfrequency': ('daily', 'weekly', 'monthly', 'quarterly'),
    'cyclecountscope': ('all', 'category', 'zone'),
}


def _labels(type_name: str) -> set[str]:
    return set(
        op.get_bind()
        .execute(
            sa.text(
                'SELECT e.enumlabel FROM pg_enum e '
                'JOIN pg_type t ON t.oid = e.enumtypid '
                'WHERE t.typname = :name'
            ),
            {'name': type_name},
        )
        .scalars()
    )


def upgrade() -> None:
    for type_name, values in _VOCABULARIES.items():
        present = _labels(type_name)
        if not present:
            # No such type on this database; nothing wrote it yet, and the
            # chain that creates it carries the values from the start.
            continue
        for value in values:
            upper = value.upper()
            if upper in present and value not in present:
                op.execute(
                    f"ALTER TYPE {type_name} RENAME VALUE '{upper}' TO '{value}'"
                )
                present.discard(upper)
                present.add(value)
        for value in values:
            if value not in present:
                op.execute(
                    f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{value}'"
                )


def downgrade() -> None:
    for type_name, values in _VOCABULARIES.items():
        present = _labels(type_name)
        for value in values:
            upper = value.upper()
            if value in present and upper not in present:
                op.execute(
                    f"ALTER TYPE {type_name} RENAME VALUE '{value}' TO '{upper}'"
                )
