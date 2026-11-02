"""audit_response_items: remember when each asset was answered

Revision ID: 010_response_item_responded_at
Revises: 009_timestamps_carry_their_zone
Create Date: 2026-10-31

A holder can now report one asset and confirm the rest in separate visits,
so the envelope's ``responded_at`` (set when the last asset is answered)
no longer says when a given report was made: the asset's timeline dated a
report by the moment its neighbours were confirmed. Each item carries its
own answer time instead.

Upgrade adds the column and fills it, for an answered item of a settled
response, from the envelope's ``responded_at`` — the only time such a row
ever had. Downgrade drops it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '010_response_item_responded_at'
down_revision: str | None = '009_timestamps_carry_their_zone'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'audit_response_items',
        sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE audit_response_items i
        SET responded_at = r.responded_at
        FROM audit_responses r
        WHERE i.response_id = r.id
          AND i.status <> 'PENDING'
          AND r.responded_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column('audit_response_items', 'responded_at')
