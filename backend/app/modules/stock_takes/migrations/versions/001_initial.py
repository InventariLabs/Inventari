"""stock_takes module baseline — create stock_takes tables.

Initial migration for the stock_takes module, extracted from core baseline_001
as part of the module migration isolation effort.

These tables were previously created by the consolidated
``baseline_001_full_schema.py``. They now belong to the stock_takes module so
that ``module enable stock_takes`` / ``module disable stock_takes`` can manage
them independently via the per-module version table
``alembic_version_stock_takes``.

Tables:
- stock_takes (includes deleted_at from core migration d1e2f3a4b5c6)
- stock_take_items
- cycle_count_schedules

Revision ID: 001_initial
Revises: None
Create Date: 2026-06-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.core.migration_helpers import create_index_if_absent, create_table_if_absent
from sqlalchemy.dialects import postgresql

revision: str = '001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ('stock_takes',)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    # Enum types — created before tables that use them.
    postgresql.ENUM(
        'draft',
        'in_progress',
        'completed',
        'cancelled',
        name='stocktakestatus',
        create_type=False,
    ).create(bind, checkfirst=True)

    postgresql.ENUM(
        'daily',
        'weekly',
        'monthly',
        'quarterly',
        name='cyclecountfrequency',
        create_type=False,
    ).create(bind, checkfirst=True)

    postgresql.ENUM(
        'all',
        'zone',
        'category',
        name='cyclecountscope',
        create_type=False,
    ).create(bind, checkfirst=True)

    # cycle_count_schedules — independent (no FK to other module tables).
    create_table_if_absent(
        'cycle_count_schedules',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column(
            'frequency',
            postgresql.ENUM(
                'daily',
                'weekly',
                'monthly',
                'quarterly',
                name='cyclecountfrequency',
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            'scope',
            postgresql.ENUM(
                'all',
                'zone',
                'category',
                name='cyclecountscope',
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('scope_filter', postgresql.JSON()),
        sa.Column('sample_size', sa.Integer()),
        sa.Column('tolerance_percent', sa.Numeric(5, 2)),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('last_run_at', sa.DateTime(timezone=True)),
        sa.Column(
            'created_by',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
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
    )
    create_index_if_absent(
        'ix_cycle_count_schedules_organization_id',
        'cycle_count_schedules',
        ['organization_id'],
    )

    # stock_takes — parent of stock_take_items.
    create_table_if_absent(
        'stock_takes',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'organization_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('organizations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'storage_location_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('storage_locations.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column(
            'status',
            postgresql.ENUM(
                'draft',
                'in_progress',
                'completed',
                'cancelled',
                name='stocktakestatus',
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('notes', sa.Text()),
        sa.Column('blind_mode', sa.Boolean(), nullable=False),
        sa.Column('require_full_count', sa.Boolean(), nullable=False),
        sa.Column('tolerance_percent', sa.Numeric(5, 2)),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
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
    )

    # stock_take_items — child of stock_takes.
    create_table_if_absent(
        'stock_take_items',
        sa.Column(
            'id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column(
            'stock_take_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('stock_takes.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('items.id', ondelete='CASCADE'),
        ),
        sa.Column('item_name', sa.String(255), nullable=False),
        sa.Column('item_brand', sa.String(255)),
        sa.Column(
            'uom_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('uoms.id'),
        ),
        sa.Column(
            'assignee_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('users.id'),
        ),
        sa.Column(
            'lot_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('stock_lots.id'),
        ),
        sa.Column('system_quantity', sa.Numeric(10, 3)),
        sa.Column('counted_quantity', sa.Numeric(10, 3)),
        sa.Column('location_in_storage', sa.String(255)),
        sa.Column('notes', sa.Text()),
        sa.Column('discrepancy_reason', sa.String(255)),
        sa.Column('is_discrepancy', sa.Integer(), nullable=False),
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
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Children first, then parents (reverse FK dependency order).
    op.drop_table('stock_take_items')
    op.drop_table('stock_takes')

    op.drop_index(
        'ix_cycle_count_schedules_organization_id',
        table_name='cycle_count_schedules',
    )
    op.drop_table('cycle_count_schedules')

    # Drop enum types.
    postgresql.ENUM(name='cyclecountscope').drop(bind, checkfirst=True)
    postgresql.ENUM(name='cyclecountfrequency').drop(bind, checkfirst=True)
    postgresql.ENUM(name='stocktakestatus').drop(bind, checkfirst=True)
