"""add require_unit_price to document_profiles.

Revision ID: doc_require_price01
Revises: doc_number_padding01
Create Date: 2026-08-13

Adds a per-organization ``require_unit_price`` flag (default False) that
turns value completeness into a hard requirement: documents cannot be
created or updated with lines missing a unit price while it is on.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_require_price01'
down_revision: str | None = 'doc_pending_approval_fix01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'document_profiles',
        sa.Column(
            'require_unit_price',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column('document_profiles', 'require_unit_price')
