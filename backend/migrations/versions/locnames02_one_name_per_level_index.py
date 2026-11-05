"""one location name per level, kept by the database

Two partial unique indexes hold the sibling-name rule: one for the places
under a parent, one for the top level, where a missing parent would otherwise
make every row distinct. ``locnames01`` has already renamed the pairs that
would have stopped them from being built.

Revision ID: locnames02
Revises: locnames01
Create Date: 2026-11-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'locnames02'
down_revision: str | None = 'locnames01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        'uq_storage_locations_org_parent_name',
        'storage_locations',
        ['organization_id', 'parent_id', 'name'],
        unique=True,
        postgresql_where=sa.text('parent_id IS NOT NULL'),
    )
    op.create_index(
        'uq_storage_locations_org_root_name',
        'storage_locations',
        ['organization_id', 'name'],
        unique=True,
        postgresql_where=sa.text('parent_id IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_storage_locations_org_root_name', table_name='storage_locations')
    op.drop_index(
        'uq_storage_locations_org_parent_name', table_name='storage_locations'
    )
