"""printing module — the label size moves from the printer to the print job.

A printer no longer has a media profile or a label size: the server draws
one label file for every printer, at the size the person chose, and the
print agent fits it to its own printer. ``print_agents`` loses ``media``,
``width_mm`` and ``height_mm``; ``print_jobs`` gains ``width_mm`` and
``height_mm``, the size of every label in the job. A job queued before this
had none of its own and printed at its printer's size; it keeps the app's
default, 50 x 24, which is what every printer was seeded with.

Revision ID: 002_label_size_on_job
Revises: 001_initial
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '002_label_size_on_job'
down_revision: str | None = '001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'print_jobs',
        sa.Column(
            'width_mm', sa.Numeric(6, 1), nullable=False, server_default='50.0'
        ),
    )
    op.add_column(
        'print_jobs',
        sa.Column(
            'height_mm', sa.Numeric(6, 1), nullable=False, server_default='24.0'
        ),
    )
    op.drop_column('print_agents', 'media')
    op.drop_column('print_agents', 'width_mm')
    op.drop_column('print_agents', 'height_mm')


def downgrade() -> None:
    op.add_column(
        'print_agents',
        sa.Column('media', sa.String(50), nullable=False, server_default='sheet'),
    )
    op.add_column(
        'print_agents',
        sa.Column(
            'width_mm', sa.Numeric(6, 1), nullable=False, server_default='50.0'
        ),
    )
    op.add_column(
        'print_agents',
        sa.Column(
            'height_mm', sa.Numeric(6, 1), nullable=False, server_default='24.0'
        ),
    )
    op.drop_column('print_jobs', 'height_mm')
    op.drop_column('print_jobs', 'width_mm')
