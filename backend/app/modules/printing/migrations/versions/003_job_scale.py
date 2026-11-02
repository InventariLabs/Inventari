"""printing module — a print job remembers how much its agent shrank it.

The server draws a label at the size the person chose, and the print agent
fits it to its printer. A label taller than the printer can print (50 x 24
on a 24 mm tape, which prints 18 mm of it) comes out scaled down; the agent
reports the scale and the job keeps it, so the Printers panel can say so.

Revision ID: 003_job_scale
Revises: 002_label_size_on_job
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '003_job_scale'
down_revision: str | None = '002_label_size_on_job'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('print_jobs', sa.Column('scale', sa.Numeric(4, 3), nullable=True))


def downgrade() -> None:
    op.drop_column('print_jobs', 'scale')
