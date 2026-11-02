"""maker module — a new organization reads production's result as a margin.

``maker_module_settings.reference_direction`` server default SAVINGS → MARGIN.
A small workshop sells what it makes, so the result it expects is the sale
price minus the cost to make; comparing against a shop price is the choice it
opts into. Rows already stored keep the direction they hold: only an
organization whose settings row does not exist yet gets the new default.

Revision ID: 015_default_result_margin
Revises: 014_add_line_shortfall
Create Date: 2026-10-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = '015_default_result_margin'
down_revision: str | None = '014_add_line_shortfall'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        'maker_module_settings',
        'reference_direction',
        server_default='MARGIN',
    )


def downgrade() -> None:
    op.alter_column(
        'maker_module_settings',
        'reference_direction',
        server_default='SAVINGS',
    )
