"""an organization can focus on a single module.

Revision ID: focfocus01
Revises: uomexact01
Create Date: 2026-09-02

Single-module mode (the FOC arc) lets an organization pick one module and have
the rest of the workspace step back. Two columns carry it:

``focus_module`` names the module the organization has focused on, or is NULL
when the organization runs the ordinary multi-module workspace. NULL is the
default and keeps today's behaviour exactly.

``pre_focus_enabled_modules`` snapshots the enabled set at the moment the
organization entered focus mode. Leaving the mode restores this snapshot — the
state before the choice, not the active profile's defaults — so switching the
mode off gives back precisely what was there. It is NULL whenever the
organization is not in focus mode.

Both are nullable and added without defaults that rewrite existing rows; every
existing organization simply reads NULL and behaves as before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'focfocus01'
down_revision: str | None = 'uomexact01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'organizations',
        sa.Column('focus_module', sa.String(length=50), nullable=True),
    )
    op.add_column(
        'organizations',
        sa.Column('pre_focus_enabled_modules', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('organizations', 'pre_focus_enabled_modules')
    op.drop_column('organizations', 'focus_module')
