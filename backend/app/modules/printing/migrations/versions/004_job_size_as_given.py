"""printing module — a print job keeps its label size and scale as given.

``print_jobs.width_mm`` and ``height_mm`` were ``Numeric(6, 1)``: a label
previewed at 50.06 mm was queued at 50.1 and printed a pixel wider than the
download. ``scale`` was ``Numeric(4, 3)``, which turns a shrink of 0.9995
into 1.000. Both are now floats, stored as the app and the agent gave them.

Revision ID: 004_job_size_as_given
Revises: 003_job_scale
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '004_job_size_as_given'
down_revision: str | None = '003_job_scale'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SIZES = ('width_mm', 'height_mm')
_DOUBLE = sa.Float(precision=53)


def upgrade() -> None:
    for column in _SIZES:
        op.alter_column(
            'print_jobs', column, type_=_DOUBLE, existing_type=sa.Numeric(6, 1)
        )
    op.alter_column(
        'print_jobs', 'scale', type_=_DOUBLE, existing_type=sa.Numeric(4, 3)
    )


def downgrade() -> None:
    op.alter_column(
        'print_jobs', 'scale', type_=sa.Numeric(4, 3), existing_type=_DOUBLE
    )
    for column in _SIZES:
        op.alter_column(
            'print_jobs', column, type_=sa.Numeric(6, 1), existing_type=_DOUBLE
        )
