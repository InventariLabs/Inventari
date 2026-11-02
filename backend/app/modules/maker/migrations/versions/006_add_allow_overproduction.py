"""maker module — add allow_overproduction to maker_module_settings.

Additive column: ``allow_overproduction BOOL DEFAULT TRUE``.  Gates whether
``complete_production`` accepts ``actual_qty > planned_qty``.

Revision ID: 006_add_allow_overproduction
Revises: 005_add_missing_fks
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '006_add_allow_overproduction'
down_revision: str | None = '005_add_missing_fks'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'maker_module_settings',
        sa.Column(
            'allow_overproduction',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('true'),
        ),
    )


def downgrade() -> None:
    op.drop_column('maker_module_settings', 'allow_overproduction')
