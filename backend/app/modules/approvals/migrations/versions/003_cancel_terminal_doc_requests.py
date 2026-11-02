"""cancel approval requests left active on terminal documents.

Revision ID: 003_cancel_terminal_doc_requests
Revises: 002_uq_workflow_org_target
Create Date: 2026-07-27

Data fix: requests created through the generic ``POST /approvals/requests``
endpoint could target documents in any state — including COMPLETED or
CANCELLED ones — because the endpoint is target-agnostic and the document
module's status guard lives only in its own proxy router. Active requests
on terminal documents are unactionable (the document can no longer
transition) and pollute the awaiting-my-approval queue; cancel them.

Guarded with ``to_regclass`` — ``documents`` is owned by the documents
module and may not exist on installs where it is disabled.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '003_cancel_terminal_doc_requests'
down_revision: str | None = '002_uq_workflow_org_target'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(sa.text('SELECT to_regclass(:name)'), {'name': f'public.{name}'}).scalar()
    )


def upgrade() -> None:
    if not (_table_exists('approval_requests') and _table_exists('documents')):
        return
    op.execute(
        sa.text(
            """
            UPDATE approval_requests
            SET status = 'CANCELLED',
                cancelled_at = now()
            WHERE target_type = 'document'
              AND status IN ('PENDING', 'IN_PROGRESS')
              AND target_id IN (
                  SELECT id FROM documents
                  WHERE status IN ('COMPLETED', 'CANCELLED')
              )
            """
        )
    )


def downgrade() -> None:
    if not (_table_exists('approval_requests') and _table_exists('documents')):
        return
    # Best-effort reverse: restore the requests to PENDING. This
    # re-creates the inconsistency the upgrade fixes, but keeps the
    # downgrade functional per project convention.
    op.execute(
        sa.text(
            """
            UPDATE approval_requests
            SET status = 'PENDING',
                cancelled_at = NULL
            WHERE target_type = 'document'
              AND status = 'CANCELLED'
              AND cancelled_by IS NULL
              AND target_id IN (
                  SELECT id FROM documents
                  WHERE status IN ('COMPLETED', 'CANCELLED')
              )
            """
        )
    )
