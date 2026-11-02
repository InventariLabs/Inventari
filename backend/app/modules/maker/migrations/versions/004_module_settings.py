"""maker module — add maker_module_settings table.

Establishes the per-module settings pattern: org_id PK, typed columns.
Initial knob: ``reference_direction`` ENUM(SAVINGS, MARGIN).

Later phases add columns additively:
: ``allow_overproduction`` BOOL
: ``availability_check_scope``, ``create_on_shortage_strategy``

Revision ID: 004_module_settings
Revises: 003_recipes_batch_yield
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '004_module_settings'
down_revision: str | None = '003_recipes_batch_yield'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'maker_module_settings',
        sa.Column(
            'organization_id',
            sa.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            primary_key=True,
        ),
        sa.Column(
            'reference_direction',
            sa.String(10),
            nullable=False,
            server_default='SAVINGS',
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table('maker_module_settings')
