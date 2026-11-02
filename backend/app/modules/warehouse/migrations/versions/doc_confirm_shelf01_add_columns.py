"""add the shelf-by-scan setting and the planned shelf of a picking line.

Revision ID: doc_confirm_shelf01
Revises: doc_packages01
Create Date: 2026-10-16

``document_profiles.confirm_shelf_by_scan`` (default False) makes a picking
or receiving session ask for the shelf's label before the product.
``wms_pick_lines.location_id`` keeps the shelf a picking line is planned
from, which the scanned label is checked against.

Downgrade drops both columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'doc_confirm_shelf01'
down_revision: str | None = 'doc_packages01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'document_profiles',
        sa.Column(
            'confirm_shelf_by_scan',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        'wms_pick_lines',
        sa.Column(
            'location_id',
            sa.Uuid(),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('wms_pick_lines', 'location_id')
    op.drop_column('document_profiles', 'confirm_shelf_by_scan')
