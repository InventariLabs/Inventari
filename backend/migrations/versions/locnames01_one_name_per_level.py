"""rename the locations that share a name with an older sibling

The service refuses a second location of the same name under one parent, but
it reads before it writes: two requests naming a place at the same moment both
found the name free and both were saved, so an organization may hold two rows
with one name where the application says that cannot happen. The next
revision puts that rule in the database as a unique index, which cannot be
built over such a pair.

Nothing is deleted and no stock moves: the later place of each pair takes a
number after its name ("Cellar (2)"), the oldest keeps its name.

Revision ID: locnames01
Revises: fieldwords01
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'locnames01'
down_revision: str | None = 'fieldwords01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``name`` is 100 characters wide; the suffix has to fit inside it.
NAME_WIDTH = 100

#: Renames every location but the oldest of each (organization, parent, name)
#: group, and answers how many it renamed. A new name can meet another
#: existing one, so the statement is repeated until it renames nothing.
RENAME_LATER_DUPLICATES = f"""
WITH ranked AS (
    SELECT id, name,
           row_number() OVER (
               PARTITION BY organization_id, parent_id, name
               ORDER BY created_at, id
           ) AS place
    FROM storage_locations
)
UPDATE storage_locations AS s
SET name = left(ranked.name, {NAME_WIDTH} - length(' (' || ranked.place || ')'))
           || ' (' || ranked.place || ')'
FROM ranked
WHERE s.id = ranked.id AND ranked.place > 1
"""


def upgrade() -> None:
    connection = op.get_bind()
    # Bounded: a pass that renames nothing ends the loop; the index would
    # refuse a name that somehow still repeats.
    for _ in range(20):
        if connection.execute(sa.text(RENAME_LATER_DUPLICATES)).rowcount == 0:
            break


def downgrade() -> None:
    """A rename is not undone: the numbered names stay."""
