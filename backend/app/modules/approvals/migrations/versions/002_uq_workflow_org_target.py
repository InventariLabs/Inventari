"""add unique constraint on approval_workflows (organization_id, target_type)

The approvals module's baseline migration ``001_initial.py`` declared
``UniqueConstraint('organization_id', 'target_type', name='uq_workflow_org_target')``
but the constraint was never actually created on existing databases
(the module migration may have been skipped during install because the
table was created earlier by core baseline_001).

Without this constraint, ``_create_workflow_impl`` had to rely on a
``SELECT ... FOR UPDATE`` lock to prevent duplicate workflows per
(org, target_type). The lock acquired a row-level lock that, under
concurrent load, caused 1.6-3.5s waits in production (see commit
d3da6286 logs from 2026-06-27 19:16:52).

This migration creates the unique index so the application code can
rely on database-enforced uniqueness instead of pessimistic locking.

Revision ID: 002_uq_workflow_org_target
Revises: 001_initial
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '002_uq_workflow_org_target'
down_revision: str | None = '001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotent: on fresh installs, 001_initial.py already created the
    # unique index via sa.UniqueConstraint(...) inside create_table. We
    # only need to create it on databases where 001_initial ran before
    # the constraint was added (i.e. databases that existed before this
    # migration).
    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = current_schema() "
            "AND indexname = 'uq_workflow_org_target'"
        )
    ).scalar()
    if not exists:
        op.create_index(
            'uq_workflow_org_target',
            'approval_workflows',
            ['organization_id', 'target_type'],
            unique=True,
        )


def downgrade() -> None:
    # ``create_index(unique=True)`` creates a UNIQUE constraint backed by
    # a btree index. To reverse, drop the constraint (which auto-drops
    # the index too); ``drop_index`` alone fails with
    # ``DependentObjectsStillExist``.
    op.drop_constraint(
        'uq_workflow_org_target', 'approval_workflows', type_='unique'
    )