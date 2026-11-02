"""printing module — a print job remembers the reads its labels answer to.

The queue's list and its retry admitted a reader of products or of shelves
alike, so a role refused a new product job read product codes off the list
and printed that job again; a shelf job the same way round. ``print_jobs``
gains ``read_permissions``: the reads, any one of which a caller needs to see
or resend the job — those of the screens that may send its kind of label,
decided when it is queued.

A job from before this revision is read for them from the labels it froze,
whose shape tells its kind apart: a label the warehouse drew carries the
address its QR opens (``qr_url``) and answers to ``warehouse:read``, the only
module that queues one; a pool label carries its ``label_id`` and answers to
``items:read`` and ``equipment:read`` (the Labels screen and the equipment
register send them); a product's barcode label is ``kind: product`` without a
QR, ``items:read``; what is left — a shelf's QR label, or its bars with the
``qr`` slot — answers to ``locations:read`` and ``warehouse:read``.

Downgrade drops the column.

Revision ID: 007_job_read_permission
Revises: 006_agent_versions
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '007_job_read_permission'
down_revision: str | None = '006_agent_versions'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'print_jobs',
        sa.Column('read_permissions', postgresql.JSONB(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE print_jobs SET read_permissions = CASE
                WHEN labels -> 0 ? 'qr_url' THEN '["warehouse:read"]'
                WHEN labels -> 0 ->> 'label_id' IS NOT NULL
                    THEN '["items:read", "equipment:read"]'
                WHEN labels -> 0 ->> 'kind' = 'product'
                     AND NOT labels -> 0 ? 'qr' THEN '["items:read"]'
                ELSE '["locations:read", "warehouse:read"]'
            END::jsonb
            """
        )
    )
    op.alter_column('print_jobs', 'read_permissions', nullable=False)


def downgrade() -> None:
    op.drop_column('print_jobs', 'read_permissions')
