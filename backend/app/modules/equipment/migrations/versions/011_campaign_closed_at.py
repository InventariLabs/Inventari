"""audit_campaigns: remember when a campaign was closed

Revision ID: 011_campaign_closed_at
Revises: 010_response_item_responded_at
Create Date: 2026-11-22

A closed campaign keeps the record it closed with, which needs the moment it
closed: an asset returned before it counts as returned, one returned afterwards
is a later custody move. Nothing stored that moment.

Upgrade adds the column and fills it for a completed or cancelled campaign
from ``updated_at``, the last time the row changed, which closing was.
Downgrade drops it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '011_campaign_closed_at'
down_revision: str | None = '010_response_item_responded_at'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'audit_campaigns',
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE audit_campaigns
        SET closed_at = updated_at
        WHERE status IN ('COMPLETED', 'CANCELLED')
        """
    )


def downgrade() -> None:
    op.drop_column('audit_campaigns', 'closed_at')
