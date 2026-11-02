"""maker module — add availability_check_scope and create_on_shortage_strategy.

Additive columns on ``maker_module_settings``:

- ``availability_check_scope VARCHAR(15) DEFAULT 'GLOBAL'``
- ``create_on_shortage_strategy VARCHAR(10) DEFAULT 'ALLOW'``

These knobs govern the availability check default scope and the
create-time reaction to ingredient shortages (ALLOW/WARN/BLOCK).

Revision ID: 007_add_availability_shortage
Revises: 006_add_allow_overproduction
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '007_add_availability_shortage'
down_revision: str | None = '006_add_allow_overproduction'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'maker_module_settings',
        sa.Column(
            'availability_check_scope',
            sa.String(15),
            nullable=False,
            server_default='GLOBAL',
        ),
    )
    op.add_column(
        'maker_module_settings',
        sa.Column(
            'create_on_shortage_strategy',
            sa.String(10),
            nullable=False,
            server_default='ALLOW',
        ),
    )


def downgrade() -> None:
    op.drop_column('maker_module_settings', 'create_on_shortage_strategy')
    op.drop_column('maker_module_settings', 'availability_check_scope')
