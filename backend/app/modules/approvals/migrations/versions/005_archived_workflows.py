"""archived workflows step aside: an archived state of their own, and the slot freed

Revision ID: 005_archived_workflows
Revises: 004_timestamps_carry_their_zone
Create Date: 2026-10-10

Deleting a workflow that had requests only switched it off. The row stayed on
the workflow list looking like any inactive workflow, and it kept the only
place ``uq_workflow_org_target`` allowed for its target type: creating the
next workflow overwrote its name and stages in place, so its past requests,
which read their stage labels from the workflow, were then read through the
new stages.

``archived_at`` is that state, apart from inactive, and the unique index now
holds only among workflows that are not archived, so the next workflow is a
new row and the archived one keeps the stages its requests were decided
under.

Backfill: until now a delete left a workflow inactive with its history, and
nothing recorded that it had been a delete — a workflow switched off by hand
looks the same. Every inactive workflow with requests and none of them open
is archived, because that is what the delete promised and what an
administrator who pressed it is still looking at. A workflow that was only
switched off and gets archived this way leaves the list with its history
intact; the next one is created from the form. One with an open request is
left as it is: it is still holding something, and the list is where that is
settled.

Downgrade refuses while a target type has more than one workflow: the old
constraint cannot hold over two rows, and deleting either would take the
history with it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '005_archived_workflows'
down_revision: str | None = '004_timestamps_carry_their_zone'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_old_rule() -> None:
    # A fresh install got the rule as a constraint (001_initial); an older
    # database got it as a plain unique index (002). Dropping the constraint
    # drops its index too, so whichever form is there goes.
    op.execute(
        'ALTER TABLE approval_workflows DROP CONSTRAINT IF EXISTS uq_workflow_org_target'
    )
    op.execute('DROP INDEX IF EXISTS uq_workflow_org_target')


def upgrade() -> None:
    op.add_column(
        'approval_workflows',
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE approval_workflows AS wf
            SET archived_at = COALESCE(wf.updated_at, wf.created_at, now())
            WHERE wf.is_active IS FALSE
              AND EXISTS (
                  SELECT 1 FROM approval_requests r WHERE r.workflow_id = wf.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM approval_requests r
                  WHERE r.workflow_id = wf.id
                    AND r.status IN ('PENDING', 'IN_PROGRESS')
              )
            """
        )
    )
    _drop_old_rule()
    op.create_index(
        'uq_workflow_org_target',
        'approval_workflows',
        ['organization_id', 'target_type'],
        unique=True,
        postgresql_where=sa.text('archived_at IS NULL'),
    )


def downgrade() -> None:
    crowded = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT count(*) FROM (
                    SELECT 1 FROM approval_workflows
                    GROUP BY organization_id, target_type
                    HAVING count(*) > 1
                ) AS crowded
                """
            )
        )
        .scalar()
    )
    if crowded:
        raise RuntimeError(
            f'{crowded} target type(s) have an archived workflow beside another '
            'one; the single-workflow rule cannot be restored without deleting '
            'the history one of them carries.'
        )
    _drop_old_rule()
    # As a constraint, the shape 001_initial builds and 002's downgrade drops.
    op.create_unique_constraint(
        'uq_workflow_org_target',
        'approval_workflows',
        ['organization_id', 'target_type'],
    )
    op.drop_column('approval_workflows', 'archived_at')
