"""rentals: kits, kit lines, and reminder markers

Revision ID: 002_kits_and_reminders
Revises: 001_initial
Create Date: 2026-11-28

A kit is a named set of assets or models booked as one. It is stored beside
the booking lines rather than in them: a line that names a kit is expanded
into one ordinary line per member, carrying the kit's id and name, so
availability and the hand-out keep working on units. A kit's code is what a
scanner reads to hand the whole set out at once.

The reminder markers close the two moments a borrower hears from the module:
once before the window ends, and once per organization-local day while the
booking is late.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.module_sdk import create_index_if_absent, create_table_if_absent
from sqlalchemy.dialects import postgresql

revision: str = '002_kits_and_reminders'
down_revision: str | None = '001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_absent(
        'rental_kits',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('code', sa.String(32), nullable=False),
        sa.Column('note', sa.Text()),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent(
        'ix_rental_kits_organization_id', 'rental_kits', ['organization_id']
    )
    create_index_if_absent(
        'uq_rental_kits_org_name',
        'rental_kits',
        ['organization_id', 'name'],
        unique=True,
    )
    create_index_if_absent(
        'uq_rental_kits_org_code',
        'rental_kits',
        ['organization_id', 'code'],
        unique=True,
    )

    create_table_if_absent(
        'rental_kit_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'kit_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('rental_kits.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('items.id', ondelete='CASCADE'),
        ),
        sa.Column('model', sa.String(255)),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint(
            '(item_id IS NOT NULL AND model IS NULL) '
            'OR (item_id IS NULL AND model IS NOT NULL)',
            name='ck_rental_kit_members_one_kind',
        ),
        sa.CheckConstraint(
            'quantity > 0', name='ck_rental_kit_members_quantity'
        ),
    )
    create_index_if_absent(
        'ix_rental_kit_members_organization_id',
        'rental_kit_members',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_rental_kit_members_kit_id', 'rental_kit_members', ['kit_id']
    )
    create_index_if_absent(
        'ix_rental_kit_members_org_kit',
        'rental_kit_members',
        ['organization_id', 'kit_id'],
    )

    op.add_column(
        'rental_booking_lines',
        sa.Column(
            'kit_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('rental_kits.id', ondelete='SET NULL'),
            nullable=True,
        ),
    )
    op.add_column(
        'rental_booking_lines',
        sa.Column('kit_name', sa.String(255), nullable=True),
    )
    create_index_if_absent(
        'ix_rental_booking_lines_kit_id', 'rental_booking_lines', ['kit_id']
    )

    op.add_column(
        'rental_bookings',
        sa.Column(
            'end_reminder_sent_at', sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        'rental_bookings',
        sa.Column('late_reminder_sent_on', sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('rental_bookings', 'late_reminder_sent_on')
    op.drop_column('rental_bookings', 'end_reminder_sent_at')
    op.drop_index('ix_rental_booking_lines_kit_id', 'rental_booking_lines')
    op.drop_column('rental_booking_lines', 'kit_name')
    op.drop_column('rental_booking_lines', 'kit_id')
    op.drop_table('rental_kit_members')
    op.drop_table('rental_kits')
