"""an approval can be spent: record when a granted request authorised its act

Revision ID: 006_consumed_approvals
Revises: 005_archived_workflows
Create Date: 2026-10-11

Some targets ask for a decision that authorises one act — an equipment
checkout is the case that made this necessary — and the gate asked only
whether the newest request was APPROVED. Nothing spent that approval, so
the row stayed APPROVED and the same decision kept opening the door for
every later checkout of the asset, for anyone. Two columns make the spend
real: ``consumed_at`` says when, ``consumed_by`` who. A target whose
approval is instead a state of the record (a document moves to CONFIRMED)
leaves both NULL and its gate keeps answering as it did.

Downgrade drops both columns; a spent approval then reads as an unspent
one, which is the behaviour this revision exists to end.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '006_consumed_approvals'
down_revision: str | None = '005_archived_workflows'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'approval_requests',
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'approval_requests',
        sa.Column('consumed_by', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        'fk_approval_requests_consumed_by_users',
        'approval_requests',
        'users',
        ['consumed_by'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_approval_requests_consumed_by_users',
        'approval_requests',
        type_='foreignkey',
    )
    op.drop_column('approval_requests', 'consumed_by')
    op.drop_column('approval_requests', 'consumed_at')
