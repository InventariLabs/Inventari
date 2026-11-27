"""rentals module baseline — bookings, lines, units, blocks and buffer rules.

Initial migration for the rentals module: one booking per promise with its
lines (an asset or a model and a count), the units a line resolves to, the
blocks that make an asset unbookable, and the buffer rules around bookings.

Revision ID: 001_initial
Revises: None
Create Date: 2026-11-26

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.module_sdk import create_index_if_absent, create_table_if_absent
from sqlalchemy.dialects import postgresql

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ('rentals',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    create_table_if_absent(
        'rental_bookings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column(
            'borrower_partner_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('partners.id', ondelete='SET NULL'),
        ),
        sa.Column(
            'borrower_user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
        ),
        sa.Column('borrower_name', sa.String(255), nullable=False),
        sa.Column('borrower_email', sa.String(255)),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('note', sa.Text()),
        sa.Column('picked_up_at', sa.DateTime(timezone=True)),
        sa.Column('returned_at', sa.DateTime(timezone=True)),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('RESERVED', 'PICKED_UP', 'RETURNED', 'CANCELLED')",
            name='ck_rental_bookings_status',
        ),
    )
    create_index_if_absent(
        'ix_rental_bookings_organization_id',
        'rental_bookings',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_rental_bookings_org_window',
        'rental_bookings',
        ['organization_id', 'starts_at', 'ends_at'],
    )
    create_index_if_absent(
        'ix_rental_bookings_org_status',
        'rental_bookings',
        ['organization_id', 'status'],
    )
    create_index_if_absent(
        'ix_rental_bookings_borrower_partner_id',
        'rental_bookings',
        ['borrower_partner_id'],
    )
    create_index_if_absent(
        'ix_rental_bookings_borrower_user_id',
        'rental_bookings',
        ['borrower_user_id'],
    )

    create_table_if_absent(
        'rental_booking_lines',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'booking_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('rental_bookings.id', ondelete='CASCADE'),
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
            name='ck_rental_booking_lines_one_kind',
        ),
        sa.CheckConstraint('quantity > 0', name='ck_rental_booking_lines_quantity'),
    )
    create_index_if_absent(
        'ix_rental_booking_lines_organization_id',
        'rental_booking_lines',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_rental_booking_lines_booking_id',
        'rental_booking_lines',
        ['booking_id'],
    )
    create_index_if_absent(
        'ix_rental_booking_lines_org_item',
        'rental_booking_lines',
        ['organization_id', 'item_id'],
    )
    create_index_if_absent(
        'ix_rental_booking_lines_org_model',
        'rental_booking_lines',
        ['organization_id', 'model'],
    )

    create_table_if_absent(
        'rental_booking_units',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'booking_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('rental_bookings.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'line_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('rental_booking_lines.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('items.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'assignment_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('equipment_assignments.id', ondelete='SET NULL'),
        ),
        sa.Column('condition', sa.String(30)),
        sa.Column('return_note', sa.Text()),
        sa.Column('returned_at', sa.DateTime(timezone=True)),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
    )
    create_index_if_absent(
        'ix_rental_booking_units_organization_id',
        'rental_booking_units',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_rental_booking_units_booking_id',
        'rental_booking_units',
        ['booking_id'],
    )
    create_index_if_absent(
        'ix_rental_booking_units_line_id',
        'rental_booking_units',
        ['line_id'],
    )
    create_index_if_absent(
        'ix_rental_booking_units_item_id',
        'rental_booking_units',
        ['item_id'],
    )
    create_index_if_absent(
        'ix_rental_booking_units_org_item',
        'rental_booking_units',
        ['organization_id', 'item_id'],
    )
    create_index_if_absent(
        'uq_rental_booking_units_line_item',
        'rental_booking_units',
        ['line_id', 'item_id'],
        unique=True,
    )

    create_table_if_absent(
        'rental_blocks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('items.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('source', sa.String(20), nullable=False),
        sa.Column(
            'booking_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('rental_bookings.id', ondelete='SET NULL'),
        ),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='SET NULL'),
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('MANUAL', 'SERVICE')", name='ck_rental_blocks_source'
        ),
        sa.CheckConstraint('ends_at > starts_at', name='ck_rental_blocks_window_order'),
    )
    create_index_if_absent(
        'ix_rental_blocks_organization_id',
        'rental_blocks',
        ['organization_id'],
    )
    create_index_if_absent(
        'ix_rental_blocks_item_id',
        'rental_blocks',
        ['item_id'],
    )
    create_index_if_absent(
        'ix_rental_blocks_org_item_window',
        'rental_blocks',
        ['organization_id', 'item_id', 'starts_at'],
    )

    create_table_if_absent(
        'rental_buffer_rules',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('model', sa.String(255)),
        sa.Column(
            'category_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('categories.id', ondelete='CASCADE'),
        ),
        sa.Column('hours_before', sa.Integer(), nullable=False),
        sa.Column('hours_after', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint(
            '(model IS NOT NULL) <> (category_id IS NOT NULL)',
            name='ck_rental_buffer_rules_one_target',
        ),
        sa.CheckConstraint(
            'hours_before >= 0 AND hours_after >= 0',
            name='ck_rental_buffer_rules_hours',
        ),
    )
    create_index_if_absent(
        'ix_rental_buffer_rules_organization_id',
        'rental_buffer_rules',
        ['organization_id'],
    )
    create_index_if_absent(
        'uq_rental_buffer_rules_org_model',
        'rental_buffer_rules',
        ['organization_id', 'model'],
        unique=True,
        postgresql_where=sa.text('model IS NOT NULL'),
    )
    create_index_if_absent(
        'uq_rental_buffer_rules_org_category',
        'rental_buffer_rules',
        ['organization_id', 'category_id'],
        unique=True,
        postgresql_where=sa.text('category_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_table('rental_buffer_rules')
    op.drop_table('rental_blocks')
    op.drop_table('rental_booking_units')
    op.drop_table('rental_booking_lines')
    op.drop_table('rental_bookings')
