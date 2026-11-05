"""write the default of the history quantity the way a fresh install does

The previous core chain created ``shopping_list_history`` itself, and its
default of one survives on such a database as ``'1'::numeric``, where a database
built from this chain holds ``1``. The value is the same; this leaves one
spelling, so comparing the two kinds of database finds nothing.

``downgrade`` leaves it: a fresh install never held the other spelling.

Revision ID: 007_history_quantity_default
Revises: 006_status_is_the_only_state
Create Date: 2026-11-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = '007_history_quantity_default'
down_revision: str | None = '006_status_is_the_only_state'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('ALTER TABLE shopping_list_history ALTER COLUMN quantity SET DEFAULT 1')


def downgrade() -> None:
    # Nothing to undo: see the module docstring.
    pass
