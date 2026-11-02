"""park CONFIRMED documents with active approval requests in PENDING_APPROVAL.

Revision ID: doc_pending_approval_fix01
Revises: doc_number_padding01
Create Date: 2026-07-27

Data fix for the "Pending Approval" filter divergence: approval requests
created through the generic ``POST /approvals/requests`` endpoint (the
``approval_status_badge`` slot on the document detail page) never flipped
the document status, so documents stayed CONFIRMED with an active request
and were invisible to the ``status=PENDING_APPROVAL`` list filter while
still showing in the awaiting-my-approval queue. The frontend now routes
through ``POST /documents/{id}/request-approval``; this
migration repairs the rows created before the fix.

Guarded with ``to_regclass`` — ``approval_requests`` is owned by the
approvals module and may not exist on installs where it is disabled.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_pending_approval_fix01'
down_revision: str | None = 'doc_number_padding01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(sa.text(f'SELECT to_regclass(:name)'), {'name': f'public.{name}'}).scalar()
    )


def upgrade() -> None:
    if not (_table_exists('documents') and _table_exists('approval_requests')):
        return
    op.execute(
        sa.text(
            """
            UPDATE documents
            SET status = 'PENDING_APPROVAL'
            WHERE status = 'CONFIRMED'
              AND id IN (
                  SELECT target_id FROM approval_requests
                  WHERE target_type = 'document'
                    AND status IN ('PENDING', 'IN_PROGRESS')
              )
            """
        )
    )


def downgrade() -> None:
    if not (_table_exists('documents') and _table_exists('approval_requests')):
        return
    # Best-effort reverse: only documents parked by a manually created
    # request (not threshold auto-created ones, which legitimately park in
    # PENDING_APPROVAL on confirm) return to CONFIRMED.
    op.execute(
        sa.text(
            """
            UPDATE documents
            SET status = 'CONFIRMED'
            WHERE status = 'PENDING_APPROVAL'
              AND id IN (
                  SELECT target_id FROM approval_requests
                  WHERE target_type = 'document'
                    AND status IN ('PENDING', 'IN_PROGRESS')
                    AND COALESCE(meta_data ->> 'auto_created', 'false') <> 'true'
              )
            """
        )
    )
