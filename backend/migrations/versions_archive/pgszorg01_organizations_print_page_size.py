"""an organization says which paper its office prints on.

Revision ID: pgszorg01
Revises: moveowner01
Create Date: 2026-10-02

Paper size is a property of the printer standing in the office, so it
belongs to the organization: print templates used to bake ``size: A4``
into every layout with no door to change it, and a customer outside Europe
printed on paper their tray does not hold.

``print_page_size`` is 'a4' or 'letter' — an explicit entry for an office
whose printer disagrees with its country. NULL is "no opinion": the
country column answers (US/CA/MX print Letter, everyone else A4). Nullable
and added without a default that rewrites existing rows; every existing
organization reads NULL and prints exactly what it printed before, now
decided in one place instead of six templates.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'pgszorg01'
down_revision: str | None = 'moveowner01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'organizations',
        sa.Column('print_page_size', sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('organizations', 'print_page_size')
