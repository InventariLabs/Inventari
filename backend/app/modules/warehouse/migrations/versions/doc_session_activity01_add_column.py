"""add the moment a scanning session was last worked on.

Revision ID: doc_session_activity01
Revises: doc_pick_line_expiry01
Create Date: 2026-10-19

``wms_pick_sessions.last_activity_at`` is when the session was last started,
resumed or scanned in. A session nobody has touched for the organization's
idle time is released: its scans stay, and the document can be completed or
continued by anyone. A session written before the column reads its start.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_session_activity01'
down_revision: str | None = 'doc_pick_line_expiry01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'wms_pick_sessions',
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('wms_pick_sessions', 'last_activity_at')
