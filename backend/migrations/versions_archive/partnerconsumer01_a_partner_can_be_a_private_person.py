"""a partner can be a private person, whom the tax-id requirement does not reach.

Revision ID: partnerconsumer01
Revises: evtoutbox03
Create Date: 2026-10-16

A Polish or German organization's documents demand the partner's tax id
before they confirm, and a private person has none to give: a dispatch to a
consumer could not be confirmed at all. ``is_consumer`` marks such a partner;
the requirement skips it. Existing partners are businesses until someone
says otherwise, so the column starts false.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'partnerconsumer01'
down_revision: str | None = 'evtoutbox03'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'partners',
        sa.Column(
            'is_consumer', sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column('partners', 'is_consumer')
