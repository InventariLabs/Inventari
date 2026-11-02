"""a location that physically moves records where it went: location_relocations

Revision ID: locreloc01
Revises: moveexpiry01
Create Date: 2026-10-19

A location keeps its id when it moves in the tree, so the movements of the
products inside cannot say by their two ends that it moved. The relocation
is the document they point at: the location, the path it left and the path
it reached. A move that only corrects the layout writes none.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'locreloc01'
down_revision: str | None = 'moveexpiry01'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'location_relocations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('location_name', sa.String(255), nullable=False),
        sa.Column(
            'from_parent_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column(
            'to_parent_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('from_path', sa.Text(), nullable=True),
        sa.Column('to_path', sa.Text(), nullable=True),
        sa.Column('moved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.create_index(
        'ix_location_relocations_org_moved_at',
        'location_relocations',
        ['organization_id', 'moved_at'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_location_relocations_org_moved_at', table_name='location_relocations'
    )
    op.drop_table('location_relocations')
