"""a pool label holds any code a location can carry.

Revision ID: poolcode01
Revises: legacyvals01
Create Date: 2026-10-22

When a location's code is renumbered, the old code stays behind as a pool
label aimed at the location, so the sticker already on the shelf keeps
scanning. A location's code may be up to 100 characters, typed by a person;
the pool's column held 20, the length of the codes it generates. It now
holds what the location column holds.

Downgrade removes the pool labels whose code would not fit back: only a
renumbered location's old code can be that long, and the location itself is
untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'poolcode01'
down_revision: str | None = 'legacyvals01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        'label_pool',
        'short_code',
        existing_type=sa.String(20),
        type_=sa.String(100),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute('DELETE FROM label_pool WHERE length(short_code) > 20')
    op.alter_column(
        'label_pool',
        'short_code',
        existing_type=sa.String(100),
        type_=sa.String(20),
        existing_nullable=False,
    )
