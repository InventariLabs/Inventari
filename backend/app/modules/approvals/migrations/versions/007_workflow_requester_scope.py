"""add requester_scope to approval_workflows: whose submissions a workflow holds

Revision ID: 007_workflow_requester_scope
Revises: 006_consumed_approvals
Create Date: 2026-10-14

A workflow said who decides and nothing about who is controlled, so an
administrator confirming a receipt was held like anyone else. The column
names whose submissions the workflow holds: everyone, or chosen people and
roles. Its default is "everyone", which is what every workflow saved before
held, so existing workflows keep their behaviour and no row is rewritten by
hand; the API asks for the choice explicitly from now on.

Downgrade drops the column; every workflow then holds everyone again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '007_workflow_requester_scope'
down_revision: str | None = '006_consumed_approvals'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'approval_workflows',
        sa.Column(
            'requester_scope',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text('\'{"everyone": true}\'::jsonb'),
        ),
    )


def downgrade() -> None:
    op.drop_column('approval_workflows', 'requester_scope')
