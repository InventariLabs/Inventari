"""drop allowed_fields from document_type_configs.

Revision ID: doc_drop_allowed_fields01
Revises: doc_require_price01
Create Date: 2026-08-18

``allowed_fields`` was stored per document type and read by nothing: which
line fields a form shows is decided by ``document_profiles.visible_line_fields``.
The rest of the type configuration now applies (default locations, partner
requirement, sequence format), so this column is the one promise left that
nothing could keep — and an API that accepts a setting it ignores is worse than
one that does not offer it.

Downgrade re-adds the column, empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'doc_drop_allowed_fields01'
down_revision: str | None = 'doc_require_price01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column('document_type_configs', 'allowed_fields')


def downgrade() -> None:
    op.add_column(
        'document_type_configs',
        sa.Column('allowed_fields', postgresql.JSONB(), nullable=True),
    )
